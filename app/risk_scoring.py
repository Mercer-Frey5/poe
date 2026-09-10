"""risk_scoring.py — punteggio di rischio IOC/osservazione da segnali esistenti
(reputation, tld sospetto, correlazione pivot, bogon). Pesi/soglie dichiarativi in
app/config/risk_weights.yaml (vocabolario controllato, fail-fast). Nessun ML: punti
espliciti e ispezionabili (`factors`), coerente col principio di confidenza onesta."""
from __future__ import annotations

from pathlib import Path

import yaml

_WEIGHTS_YAML = Path(__file__).resolve().parent / "config" / "risk_weights.yaml"

with open(_WEIGHTS_YAML, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)

_WEIGHTS: dict = _CONFIG["weights"]
_PIVOT_THRESHOLD: int = _CONFIG["pivot_threshold"]
_DOMAIN_YOUNG_DAYS: int = _CONFIG["domain_young_days"]
_BUCKETS: list = sorted(_CONFIG["buckets"], key=lambda b: b["min_score"], reverse=True)

_LEVEL_RANK = {"critico": 3, "sospetto": 2, "basso": 1}


def _bucket_for(score: int) -> str | None:
    for b in _BUCKETS:
        if score >= b["min_score"]:
            return b["level"]
    return None


def compute_risk(entity: dict, pivot_count: int = 0) -> dict:
    """Punteggio di rischio per una entità (dict da Entity.to_dict()).
    Bogon (IP interno/non instradabile) -> sempre 0, nessun target esterno."""
    metadata = entity.get("metadata") or {}
    if metadata.get("bogon"):
        return {"score": 0, "level": None, "factors": []}

    score = 0
    factors: list[str] = []

    reputation = metadata.get("reputation") or {}
    if reputation.get("malicious"):
        score += _WEIGHTS["reputation_malicious"]
        sources = ",".join(reputation.get("sources", [])) or "?"
        factors.append(f"reputation:{sources}")

    if metadata.get("suspicious_tld"):
        score += _WEIGHTS["suspicious_tld"]
        factors.append("tld_sospetto")

    creation_date = metadata.get("creation_date")
    if creation_date:
        from datetime import date
        try:
            age_days = (date.today() - date.fromisoformat(creation_date)).days
            if age_days < _DOMAIN_YOUNG_DAYS:
                score += _WEIGHTS["domain_young"]
                factors.append("dominio_giovane")
        except ValueError:
            pass

    if pivot_count >= _PIVOT_THRESHOLD:
        score += _WEIGHTS["pivot_correlated"]
        factors.append(f"correlato_in_{pivot_count}_oss")

    return {"score": score, "level": _bucket_for(score), "factors": factors}


def aggregate_observation_risk(risks: list[dict]) -> dict:
    """Aggrega i compute_risk di un'osservazione: conteggio per livello + livello più alto."""
    counts = {"critico": 0, "sospetto": 0, "basso": 0}
    for r in risks:
        lvl = r.get("level")
        if lvl in counts:
            counts[lvl] += 1
    overall = None
    best_rank = 0
    for lvl, n in counts.items():
        if n > 0 and _LEVEL_RANK[lvl] > best_rank:
            best_rank = _LEVEL_RANK[lvl]
            overall = lvl
    return {"counts": counts, "overall_level": overall}
