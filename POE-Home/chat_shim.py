# POE-Home/chat_shim.py
"""Shim helpers per /v1/chat/completions: parsing tool-call Hermes XML di Qwen
e normalizzazione messaggi OpenAI -> chat template."""
import json
import logging
import re

logger = logging.getLogger(__name__)

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=([^>\s]+)>(.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
_PARAM_RE = re.compile(r"<parameter=([^>\s]+)>\n?(.*?)\n?</parameter>", re.DOTALL)


def parse_tool_calls(text: str) -> tuple[str | None, list[dict]]:
    """Estrae i blocchi <tool_call> Hermes XML e li converte in formato OpenAI.

    Ritorna (content, tool_calls):
    - nessun blocco -> (testo originale, [])
    - blocchi presenti -> (testo prima del primo blocco o None, lista tool_calls)
    """
    matches = list(_TOOL_CALL_RE.finditer(text))
    if not matches:
        if "<tool_call>" in text:
            logger.warning("Blocco <tool_call> malformato, trattato come testo: %r", text[:200])
        return text, []

    calls = []
    for i, m in enumerate(matches):
        args = {k: v for k, v in _PARAM_RE.findall(m.group(2))}
        calls.append({
            "id": f"call_{i}",
            "type": "function",
            "function": {
                "name": m.group(1),
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        })
    content = text[: matches[0].start()].strip()
    return (content or None), calls


def normalize_messages(msgs: list[dict]) -> list[dict]:
    """Prepara i messaggi OpenAI per apply_chat_template di Qwen:
    - content None -> "" (il template Jinja non gestisce null)
    - function.arguments stringa JSON -> dict (il template itera arguments|items)
    """
    for m in msgs:
        if m.get("content") is None:
            m["content"] = ""
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            if isinstance(fn.get("arguments"), str):
                try:
                    fn["arguments"] = json.loads(fn["arguments"])
                except ValueError:
                    fn["arguments"] = {}
    return msgs
