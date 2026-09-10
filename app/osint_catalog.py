"""osint_catalog.py — catalogo dichiarativo di risorse OSINT per tipo di entità.
Fonte: app/config/osint_catalog.yaml. Fail-fast su file mancante/malformato o
risorsa senza i campi minimi (id, kind, name, applies_to.entity_types,
validation_status) — nessun fallback silenzioso, coerente con tld_list.yaml."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import yaml

_CATALOG_YAML = Path(__file__).resolve().parent / "config" / "osint_catalog.yaml"

_REQUIRED_FIELDS = ("id", "kind", "name", "validation_status")


def _validate_resource(r: dict) -> None:
    for field in _REQUIRED_FIELDS:
        if not r.get(field):
            raise RuntimeError(f"osint_catalog.yaml: risorsa senza campo obbligatorio '{field}': {r}")
    entity_types = (r.get("applies_to") or {}).get("entity_types")
    if not entity_types:
        raise RuntimeError(f"osint_catalog.yaml: risorsa senza applies_to.entity_types: {r.get('id')}")


def load_catalog() -> list[dict]:
    """Carica tutte le risorse dal file. RuntimeError su file mancante/malformato
    o risorsa senza i campi minimi."""
    if not _CATALOG_YAML.exists():
        raise RuntimeError(f"file config mancante: {_CATALOG_YAML}")
    with _CATALOG_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    resources = (data or {}).get("resources")
    if not isinstance(resources, list) or not resources:
        raise RuntimeError(f"file config malformato o senza risorse: {_CATALOG_YAML}")
    for r in resources:
        _validate_resource(r)
    return resources


_CATALOG = load_catalog()
_BY_TYPE: dict[str, list[dict]] = {}
for _r in _CATALOG:
    for _t in _r["applies_to"]["entity_types"]:
        _BY_TYPE.setdefault(_t, []).append(_r)


def resources_for_type(entity_type: str) -> list[dict]:
    """Risorse del catalogo pertinenti per un tipo di entità. [] se nessuna."""
    return _BY_TYPE.get(entity_type, [])


def resource_url(resource: dict, value: str) -> str | None:
    """URL cliccabile per questa risorsa e questo valore. Usa url_template
    (con {value} URL-encoded) se presente, altrimenti l'url della homepage.
    None se il template è malformato (la risorsa va skippata, non deve
    rompere il render dell'intera card)."""
    template = resource.get("url_template")
    if template:
        try:
            return template.format(value=quote(value, safe=""))
        except (KeyError, IndexError, ValueError):
            return None
    return resource.get("url") or None
