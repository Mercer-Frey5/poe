"""
config_loader.py — helper condiviso per caricare config YAML.

Tre extractor di POE caricano liste YAML al modulo-load:
  - regex_extractor.py: tld_list.yaml, suspicious_tlds.yaml
  - spacy_extractor.py: stoplist_person_name.yaml

Pre-v0.5 ogni file aveva il proprio loader (3 copie quasi identiche).
Questo modulo unifica il caricamento + validazione fail-fast.

Strategia errori: tutti i loader sollevano RuntimeError esplicito al
boot se il file manca o è malformato. Niente fallback silenzioso.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent / "config"


def load_yaml_list(filename: str, *, allow_empty: bool = False) -> list[str]:
    """Carica un file YAML in app/config/ come lista di stringhe.

    Args:
        filename: nome file (es. "tld_list.yaml")
        allow_empty: se True accetta lista vuota (default False = errore)

    Returns:
        Lista di stringhe (None e stringhe vuote scartate)

    Raises:
        RuntimeError: file mancante, non lista, o vuoto (se allow_empty=False)
    """
    yaml_path = _CONFIG_DIR / filename
    if not yaml_path.exists():
        raise RuntimeError(f"file config mancante: {yaml_path}")
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise RuntimeError(f"file config malformato (atteso list): {yaml_path}")
    if not allow_empty and not data:
        raise RuntimeError(f"file config vuoto: {yaml_path}")
    return [str(v) for v in data if v is not None and str(v).strip()]
