"""
POE Voice Server
WS   /ws/speak  -> LLM -> TTS -> RVC (200e, fcpe) -> audio + testo sincronizzati
POST /speak     -> endpoint HTTP legacy
"""

import asyncio
import io
import platform
import socket
import subprocess
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from agents import general_agent, router
from agents.persona import SYSTEM_PROMPT

_llm_pool = ThreadPoolExecutor(max_workers=1)
_tts_pool = ThreadPoolExecutor(max_workers=1)
_rvc_pool = ThreadPoolExecutor(max_workers=1)

# ── Paths ──────────────────────────────────────────────────────────────────
HOME_DIR   = Path(__file__).parent
ACTIVE_VOICE = "poe"
_voices_dir  = HOME_DIR / "voices"
REF_AUDIO    = _voices_dir / ACTIVE_VOICE / "ref.wav"
RVC_MODEL    = HOME_DIR / "rvc_model" / "poe-ita_200e_4200s.pth"
RVC_INDEX    = HOME_DIR / "rvc_model" / "poe-ita.index"

LLM_MODEL = "mlx-community/Qwen3.5-4B-OptiQ-4bit"

# ── Motore TTS: "qwen" o "kokoro" — cambia questa riga per tornare indietro ──
TTS_ENGINE = "kokoro"

TTS_MODEL_QWEN   = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
TTS_MODEL_KOKORO = "mlx-community/Kokoro-82M-bf16"
KOKORO_VOICE     = "im_nicola"

_llm_model        = None
_llm_tok          = None
_tts_model_worker = None
_ref_audio_arr    = None
_tts_sr           = 24000
_ready            = False
_rvc_pipeline     = None
_boot_ts          = time.time()

# Moduli di contorno — stato statico finché non sono collegati (fase AGNO).
# OSINT gira standalone sulla stessa porta 8000: non può convivere con POE-Home.
MODULES = [
    {"nome": "OSINT",   "stato": "standalone v0.3 — non collegato"},
    {"nome": "DIARIO",  "stato": "in sviluppo"},
    {"nome": "ANALISI", "stato": "in sviluppo"},
]
_ref_text = (_voices_dir / ACTIVE_VOICE / "ref.txt").read_text().strip()


# ── Worker-thread loaders ──────────────────────────────────────────────────

_prompt_cache = None
_cache_snap   = None
_prefix_ids   = None

def _snap_state(cache):
    import mlx.core as mx
    return [
        [mx.array(a) for a in c.state] if isinstance(c.state, (list, tuple))
        else mx.array(c.state)
        for c in cache
    ]

def _restore_state(cache, snap):
    import mlx.core as mx
    for c, s in zip(cache, snap):
        c.state = [mx.array(a) for a in s] if isinstance(s, list) else mx.array(s)

def _llm_load():
    global _llm_model, _llm_tok, _prompt_cache, _cache_snap, _prefix_ids
    from mlx_lm import load as llm_load
    _llm_model, _llm_tok = llm_load(LLM_MODEL)

    # Prompt cache: KV del system prompt (costante) calcolato una volta al boot.
    # Qwen3.5 usa ArraysCache (non trimmabile) → snapshot/restore dello stato.
    try:
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache
        marker = "@@POE_MARKER@@"
        tpl = _llm_tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user",   "content": marker}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        prefix_str = tpl.split(marker)[0]
        _prefix_ids = _llm_tok.encode(prefix_str)
        _prompt_cache = make_prompt_cache(_llm_model)
        _llm_model(mx.array(_prefix_ids)[None], cache=_prompt_cache)
        mx.eval([c.state for c in _prompt_cache])
        _cache_snap = _snap_state(_prompt_cache)
        print(f"[POE] Prompt cache: {len(_prefix_ids)} token pre-calcolati.")
    except Exception as e:
        print(f"[POE] Prompt cache non disponibile ({e}) — uso percorso standard.")
        _prompt_cache = None


def _tts_load():
    global _tts_model_worker, _ref_audio_arr, _tts_sr
    from mlx_audio.tts.utils import load_model
    from mlx_audio.utils import load_audio
    if TTS_ENGINE == "kokoro":
        _tts_model_worker = load_model(TTS_MODEL_KOKORO)
        _tts_sr = getattr(_tts_model_worker, "sample_rate", 24000)
    else:
        _tts_model_worker = load_model(TTS_MODEL_QWEN)
        _tts_sr = getattr(_tts_model_worker, "sample_rate", 24000)
        _ref_audio_arr = load_audio(str(REF_AUDIO), sample_rate=_tts_sr)


def _rvc_load():
    global _rvc_pipeline
    from mlx_rvc import RVCPipeline

    # mlx-rvc==0.1.0 ContentVec output is 50fps (hop=320@16kHz), but the
    # v2/40kHz synthesizer and RMVPE f0 (hop=160 -> 100fps) expect 100fps.
    # Without this 2x upsample the converted audio is exactly half-length
    # (plays at 2x speed). Patched here since it's missing upstream.
    if not getattr(RVCPipeline, "_poe_contentvec_patched", False):
        _orig_extract_contentvec = RVCPipeline._extract_contentvec

        def _extract_contentvec_fixed(self, audio):
            features = _orig_extract_contentvec(self, audio)
            return np.repeat(features, 2, axis=1)

        RVCPipeline._extract_contentvec = _extract_contentvec_fixed
        RVCPipeline._poe_contentvec_patched = True

    _rvc_pipeline = RVCPipeline.from_pretrained(str(RVC_MODEL))
    print("[POE] RVC pronto.")


# ── Stato di sistema ────────────────────────────────────────────────────────

_GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI   = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _device_str() -> str:
    try:
        chip = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip() or platform.machine()
    except Exception:
        chip = platform.machine()
    total_gb = round(psutil.virtual_memory().total / 2**30)
    return f"{platform.node().removesuffix('.local')} ({chip}, {total_gb}GB)"


_DEVICE = _device_str()


def _battery() -> str:
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                             text=True, timeout=2).stdout
        for part in out.split(";"):
            if "%" in part:
                pct = part.split()[-1].strip()
                stato = "in carica" if "charging" in out and "discharging" not in out else \
                        "carica completa" if "charged" in out else "su batteria"
                return f"{pct} {stato}"
    except Exception:
        pass
    return "n/d"


def _net_online() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=0.6):
            return True
    except OSError:
        return False


def _uptime_str() -> str:
    s = int(time.time() - _boot_ts)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _data_ita(now: datetime) -> str:
    return (f"{_GIORNI[now.weekday()]} {now.day} {_MESI[now.month - 1]} {now.year}, "
            f"{now.strftime('%H:%M')}")


def _get_status() -> dict:
    comp = {
        "llm": "ok" if _llm_model is not None else "non caricato",
        "tts": "ok" if _tts_model_worker is not None else "non caricato",
        "rvc": "ok" if _rvc_pipeline is not None else "fermo",
    }
    vm = psutil.virtual_memory()
    return {
        "poe": {
            "stato": "operativo" if all(v == "ok" for v in comp.values()) else "degradato",
            "uptime": _uptime_str(),
            "componenti": comp,
        },
        "sistema": {
            "data": _data_ita(datetime.now()),
            "device": _DEVICE,
            "ram_libera_gb": round(vm.available / 2**30, 1),
            "batteria": _battery(),
            "rete": "online" if _net_online() else "offline",
        },
        "moduli": MODULES,
    }


def _context_block() -> str:
    """Blocco di contesto prepeso al messaggio utente (MAI nel system prompt:
    invaliderebbe la prompt cache pre-calcolata al boot)."""
    s = _get_status()
    sis, poe = s["sistema"], s["poe"]
    comp_ok = all(v == "ok" for v in poe["componenti"].values())
    sistemi = "tutti operativi" if comp_ok else \
        ", ".join(f"{k} {v}" for k, v in poe["componenti"].items())
    return (
        "[CONTESTO SISTEMA — usa queste informazioni solo se pertinenti alla domanda, "
        "altrimenti ignorale e non menzionarle]\n"
        f"Data e ora: {sis['data']}\n"
        f"Dispositivo: {sis['device']} — batteria {sis['batteria']}, "
        f"RAM libera {sis['ram_libera_gb']}GB, rete {sis['rete']}\n"
        f"Sistemi POE: {sistemi}, attivo da {poe['uptime']}"
    )


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ready
    loop = asyncio.get_running_loop()
    print("[POE] Caricamento LLM (Qwen3.5-4B)...")
    await loop.run_in_executor(_llm_pool, _llm_load)
    print("[POE] Caricamento TTS...")
    await loop.run_in_executor(_tts_pool, _tts_load)
    print("[POE] Caricamento RVC...")
    await loop.run_in_executor(_rvc_pool, _rvc_load)
    print(f"[POE] Ref: {_ref_text}")
    _ready = True
    print("[POE] Pronto.")
    yield


app = FastAPI(lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ready": _ready}

@app.get("/status")
def status():
    return _get_status()

@app.post("/log")
async def log_msg(request: Request):
    body = await request.json()
    print(f"[STT] {body.get('msg','')}", flush=True)
    return {}

@app.get("/")
def index():
    return HTMLResponse((HOME_DIR / "home_v1.html").read_text())

@app.get("/logo")
def logo():
    return FileResponse(HOME_DIR / "Logo 1.png")

@app.get("/ack/{n}")
def serve_ack(n: int):
    p = HOME_DIR / "ack" / f"ack_{n}.wav"
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(p), media_type="audio/wav")


# ── Core ────────────────────────────────────────────────────────────────────

def _trim_to_sentence(text: str) -> str:
    """Rimuove testo dopo l'ultima punteggiatura — evita frasi troncate dal token limit."""
    for punct in ("!", "?", "."):
        idx = text.rfind(punct)
        if idx > len(text) // 3:
            return text[:idx + 1].strip()
    return text.strip()


def _get_llm_response(user_text: str, on_token=None) -> str:
    """Genera la risposta. Se on_token e' fornito, riceve ogni delta di testo
    durante la generazione e None alla fine."""
    from mlx_lm import stream_generate

    # Contesto dinamico nel messaggio utente, non nel system prompt:
    # il system prompt è congelato nella prompt cache calcolata al boot.
    user_text = _context_block() + "\n\n" + user_text

    prompt = None
    use_cache = False
    if _prompt_cache is not None:
        full_ids = _llm_tok.encode(
            _llm_tok.apply_chat_template(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user",   "content": user_text}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
        )
        # il prefisso tokenizzato deve combaciare col cache, altrimenti fallback
        if full_ids[:len(_prefix_ids)] == _prefix_ids:
            prompt = full_ids[len(_prefix_ids):]
            use_cache = True

    if not use_cache:
        prompt = _llm_tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user",   "content": user_text}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )

    kwargs = {"max_tokens": 80}
    if use_cache:
        # ripristina il cache allo stato "solo system prompt" prima di generare
        _restore_state(_prompt_cache, _cache_snap)
        kwargs["prompt_cache"] = _prompt_cache

    full = ""
    try:
        for resp in stream_generate(_llm_model, _llm_tok, prompt=prompt, **kwargs):
            full += resp.text
            if on_token and resp.text:
                on_token(resp.text)
    finally:
        # SEMPRE sbloccare il websocket, anche su eccezione
        if on_token:
            on_token(None)

    return _trim_to_sentence(full.strip())


def _get_chat_response(messages: list[dict], max_tokens: int = 300) -> str:
    """Risposta grezza per lo shim /v1/chat/completions: nessun context block,
    nessun trim a frase (l'output e' JSON, non prosa libera)."""
    from mlx_lm import stream_generate

    full_ids = _llm_tok.encode(
        _llm_tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
    )
    prompt, use_cache = full_ids, False
    if _prompt_cache is not None and full_ids[:len(_prefix_ids)] == _prefix_ids:
        prompt = full_ids[len(_prefix_ids):]
        use_cache = True

    kwargs = {"max_tokens": max_tokens}
    if use_cache:
        _restore_state(_prompt_cache, _cache_snap)
        kwargs["prompt_cache"] = _prompt_cache

    full = ""
    for resp in stream_generate(_llm_model, _llm_tok, prompt=prompt, **kwargs):
        full += resp.text
    return full.strip()


def _pcm_to_wav(audio: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _tts_synth(text: str) -> bytes:
    if TTS_ENGINE == "kokoro":
        gen = _tts_model_worker.generate(
            text=text, voice=KOKORO_VOICE, lang_code="i",
            speed=1.0, verbose=False,
        )
    else:
        gen = _tts_model_worker.generate(
            text=text, ref_audio=_ref_audio_arr, ref_text=_ref_text,
            lang_code="it", verbose=False,
        )
    chunks = [np.array(r.audio, dtype=np.float32) for r in gen]
    return _pcm_to_wav(np.concatenate(chunks), _tts_sr)


def run_rvc(input_wav: str, out_wav: str) -> str:
    if _rvc_pipeline is None:
        _rvc_load()
    _rvc_pipeline.convert(
        input_path=input_wav,
        output_path=out_wav,
        f0_shift=4,
        f0_method="rmvpe",
        index_path=str(RVC_INDEX),
        index_rate=0.5,
    )
    return out_wav


# ── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws/speak")
async def ws_speak(ws: WebSocket):
    await ws.accept()
    try:
        data = await ws.receive_json()
        user_text = data.get("text", "")
        loop = asyncio.get_running_loop()
        t0 = time.time()

        module = router.route(user_text)
        if module:
            result = router.placeholder_response(module)
        else:
            result = await general_agent.run(user_text)

        llm_text = result.verbal
        t1 = time.time()
        print(f"[TIME] LLM: {t1-t0:.1f}s  '{llm_text[:70]}'")

        tts_bytes = await loop.run_in_executor(_tts_pool, _tts_synth, llm_text)
        t2 = time.time()
        print(f"[TIME] TTS: {t2-t1:.1f}s")

        req_dir = Path(tempfile.mkdtemp())
        (req_dir / "tts.wav").write_bytes(tts_bytes)

        rvc_out = await loop.run_in_executor(
            _rvc_pool, run_rvc, str(req_dir / "tts.wav"), str(req_dir / "rvc.wav")
        )
        t3 = time.time()
        print(f"[TIME] RVC: {t3-t2:.1f}s | TOTAL: {t3-t0:.1f}s")

        audio_bytes = Path(rvc_out).read_bytes()

        await ws.send_json({"type": "text", "content": llm_text})
        await ws.send_json({
            "type": "visual",
            "content": result.visual.model_dump() if result.visual else None,
        })
        await ws.send_bytes(audio_bytes)
        await ws.send_json({"type": "done"})
        await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await ws.send_json({"type": "error", "content": str(e)})
            await ws.close()
        except Exception:
            pass


# ── HTTP legacy ─────────────────────────────────────────────────────────────

class SpeakRequest(BaseModel):
    text: str

@app.post("/speak")
async def speak(req: SpeakRequest):
    loop = asyncio.get_running_loop()
    t0 = time.time()
    llm_text = await loop.run_in_executor(_llm_pool, _get_llm_response, req.text)
    tts_bytes = await loop.run_in_executor(_tts_pool, _tts_synth, llm_text)
    req_dir = Path(tempfile.mkdtemp())
    (req_dir / "tts.wav").write_bytes(tts_bytes)
    rvc_out = await loop.run_in_executor(
        _rvc_pool, run_rvc, str(req_dir / "tts.wav"), str(req_dir / "rvc.wav")
    )
    print(f"[TIME] TOTAL: {time.time()-t0:.1f}s")
    return StreamingResponse(
        iter([Path(rvc_out).read_bytes()]),
        media_type="audio/wav",
        headers={"X-POE-Text": llm_text},
    )


# ── Shim OpenAI-compatibile per AGNO (loopback, in-process) ─────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    loop = asyncio.get_running_loop()
    msgs = [m.model_dump() for m in req.messages]
    content = await loop.run_in_executor(_llm_pool, _get_chat_response, msgs)
    return {
        "id": "chatcmpl-poe",
        "object": "chat.completion",
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
