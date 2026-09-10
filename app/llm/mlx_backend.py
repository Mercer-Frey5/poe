"""MLX LLM backend for POE — Apple Silicon nativo.

Su questa macchina (M1) l'inferenza gira in MLX, non Ollama. mlx-lm e' importato
LAZY (solo quando il backend serve) cosi' il repo resta installabile/eseguibile
anche dove MLX non c'e' (Docker/Linux -> usare OllamaBackend).

NOTA THREAD: lo stream GPU MLX e' legato al thread che carica il modello. Tutte le
chiamate MLX girano su UN solo thread (ThreadPoolExecutor max_workers=1), come in
l'hub vocale, per evitare 'no Stream(gpu) in current thread'.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.llm.base import LLMBackend

logger = logging.getLogger(__name__)

__all__ = ["MLXBackend"]


class MLXBackend(LLMBackend):
    def __init__(self, model: str, temperature: float = 0.1, max_tokens: int = 1100) -> None:
        self._model_id = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._pool = ThreadPoolExecutor(max_workers=1)   # MLX: un thread fisso
        self._model = None
        self._tok = None

    @property
    def model_name(self) -> str:
        return self._model_id

    # --- girano sul thread _pool (contesto GPU MLX) ---
    def _ensure_loaded(self) -> None:
        if self._model is None:
            from mlx_lm import load
            logger.info("MLXBackend: carico %s", self._model_id)
            self._model, self._tok = load(self._model_id)

    def _generate_sync(self, prompt: str, system: str) -> str:
        from mlx_lm import stream_generate
        try:
            from mlx_lm.sample_utils import make_sampler
            sampler = make_sampler(temp=self._temperature)
        except Exception:
            sampler = None
        self._ensure_loaded()
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        text = None
        if getattr(self._tok, "chat_template", None):
            try:   # niente reasoning verboso sui modelli 'thinking' (es. Qwen)
                text = self._tok.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            except TypeError:
                text = self._tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            except Exception:
                text = None
        if text is None:   # modello BASE senza chat template -> formato Llama-3.1 manuale
            sysp = system or "Sei un assistente preciso e conciso."
            text = ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
                    f"{sysp}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                    f"{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")
        kw = {"sampler": sampler} if sampler else {}
        # NB: niente prompt_cache condiviso. stream_generate (in questo path) NON
        # fa prefix-trim: un cache riusato accoderebbe il nuovo prompt sullo stato
        # della chiamata precedente → contaminazione tra system prompt diversi
        # (entity-ai vs synthesis) + crescita KV illimitata. Un cache fresco per
        # chiamata non darebbe alcun riuso. Quindi: nessun cache.
        out = "".join(r.text for r in stream_generate(
            self._model, self._tok, prompt=text, max_tokens=self._max_tokens, **kw))
        # Libera i buffer transitori della generazione: senza, la memoria MLX cresce
        # a ogni Sintesi/entity-ai (misurato: picco fino a ~7GB). I pesi del modello
        # NON vengono toccati (clear_cache libera solo la cache riusabile).
        import mlx.core as mx
        mx.clear_cache()
        # Via eventuali tag di reasoning (<think>...</think>): teniamo la risposta.
        if "</think>" in out:
            out = out.rsplit("</think>", 1)[-1]
        return out.strip()

    async def generate(self, prompt: str, system: str = "") -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._generate_sync, prompt, system)

    def unload(self) -> None:
        """Sfratta il modello dalla VRAM Metal (handoff con l'hub). Idempotente:
        si ricarica lazy al prossimo generate via _ensure_loaded."""
        self._model = None
        self._tok = None
        import gc
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass

    async def is_available(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._pool, self._ensure_loaded)
            return True
        except Exception:
            logger.exception("MLXBackend non disponibile per %s", self._model_id)
            return False
