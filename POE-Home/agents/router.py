from pathlib import Path

import yaml

from .dual_output import DualOutput

_MODULES_DIR = Path(__file__).parent / "modules"


def _load_modules() -> dict[str, dict]:
    modules = {}
    for d in sorted(_MODULES_DIR.iterdir()):
        if not d.is_dir():
            continue
        f = d / "module.yaml"
        if f.exists():
            modules[d.name] = yaml.safe_load(f.read_text())
    return modules


_MODULES = _load_modules()


def route(user_text: str) -> str | None:
    text = user_text.lower()
    for name, cfg in _MODULES.items():
        if any(kw.lower() in text for kw in cfg.get("trigger_keywords", [])):
            return name
    return None


def placeholder_response(module_name: str) -> DualOutput:
    cfg = _MODULES[module_name]
    return DualOutput(
        verbal=f"Il modulo {cfg['display_name']} non e' ancora collegato, "
               f"Signore. Sta arrivando, le assicuro.",
        visual=None,
    )
