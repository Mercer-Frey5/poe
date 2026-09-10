"""
runner.py — parser e runner dei test di accettazione basati su YAML.

Storia versioni dei tipi supportati:
  - v0.1: email, ipv4, url, domain, hash_md5, username, phone, person_name
  - v0.2: + hash_sha256, cve
  - v0.4: + tax_id, vat_id, social_handle, birth_date

Il runner verifica:
  - Entità attese di tipo presente in SUPPORTED_TYPES → must_extract
  - Entità vietate di tipo presente in SUPPORTED_TYPES → must_not_extract

Ignora silenziosamente:
  - Asserzioni su flag (non esistono in v0.4 base)
  - Asserzioni su relazioni (in arrivo v0.5 con derived_from)
  - Entità attese/vietate di tipi non ancora supportati
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import Entity


SUPPORTED_TYPES = frozenset({
    "email", "ipv4", "url", "domain",
    "hash_md5", "hash_sha256", "cve",
    "username", "phone", "person_name",
    # v0.4
    "tax_id", "vat_id", "social_handle", "birth_date",
})

# Alias backward-compat: prima si chiamava V0_2_TYPES (pre-rename v0.4).
V0_2_TYPES = SUPPORTED_TYPES


@dataclass
class AcceptanceCase:
    id: str
    title: str
    input_text: str
    must_extract: list[tuple[str, str]]
    must_not_extract: list[tuple[str, str]]

    @classmethod
    def from_yaml(cls, path: Path) -> "AcceptanceCase":
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        meta = data.get("metadata", {})
        tc_id = meta.get("id", path.stem)
        title = meta.get("title", "")

        input_text = data.get("input", {}).get("text", "") or ""

        must_extract = _extract_entity_tuples(
            data.get("must_extract", {}).get("entities", [])
        )
        must_not_extract = _extract_entity_tuples(
            data.get("must_not_extract", {}).get("entities", [])
        )

        return cls(
            id=tc_id,
            title=title,
            input_text=input_text,
            must_extract=must_extract,
            must_not_extract=must_not_extract,
        )


def _extract_entity_tuples(raw: list[dict]) -> list[tuple[str, str]]:
    """Filtra per i soli tipi supportati (v0.4 base)."""
    out: list[tuple[str, str]] = []
    for item in raw:
        t = item.get("type")
        v = item.get("value")
        if t in SUPPORTED_TYPES and v:
            if t in ("domain", "hash_md5", "hash_sha256"):
                v = v.lower()
            out.append((t, v))
    return out


def check_case(case: AcceptanceCase, extracted: list[Entity]) -> list[str]:
    """Confronta l'output con le attese. Lista vuota = caso superato."""
    extracted_set = {(e.type, e.value) for e in extracted}
    violations: list[str] = []

    for t, v in case.must_extract:
        if (t, v) not in extracted_set:
            violations.append(f"mancante: [{t}] {v}")

    for t, v in case.must_not_extract:
        if (t, v) in extracted_set:
            violations.append(f"non atteso: [{t}] {v}")

    return violations
