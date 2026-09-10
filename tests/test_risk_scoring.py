"""Task 1: compute_risk + aggregate_observation_risk (modulo puro, no I/O oltre yaml)."""
from datetime import date, timedelta

from app.risk_scoring import compute_risk, aggregate_observation_risk


def _entity(metadata=None, **kw):
    base = {"type": "ipv4", "value": "9.9.9.9", "original": "9.9.9.9",
            "confidence": "medium", "metadata": metadata or {}, "derived_from": None}
    base.update(kw)
    return base


def test_reputation_malicious_alone_is_critico():
    r = compute_risk(_entity(metadata={"reputation": {"malicious": True, "sources": ["threatfox"]}}))
    assert r["score"] == 100
    assert r["level"] == "critico"
    assert any("reputation" in f for f in r["factors"])


def test_suspicious_tld_alone_is_sospetto():
    r = compute_risk(_entity(metadata={"suspicious_tld": True}))
    assert r["score"] == 30
    assert r["level"] == "sospetto"
    assert "tld_sospetto" in r["factors"]


def test_pivot_alone_is_basso():
    r = compute_risk(_entity(), pivot_count=3)
    assert r["score"] == 10
    assert r["level"] == "basso"
    assert any("correlato" in f for f in r["factors"])


def test_pivot_below_threshold_not_counted():
    r = compute_risk(_entity(), pivot_count=2)
    assert r["score"] == 0
    assert r["level"] is None


def test_combination_sums_and_buckets():
    r = compute_risk(_entity(metadata={"suspicious_tld": True}), pivot_count=5)
    assert r["score"] == 40           # 30 + 10
    assert r["level"] == "sospetto"   # 40 >= 30 ma < 100
    assert len(r["factors"]) == 2


def test_bogon_forces_zero_even_with_reputation():
    r = compute_risk(_entity(metadata={"bogon": True, "bogon_type": "private",
                                       "reputation": {"malicious": True, "sources": ["x"]}}))
    assert r == {"score": 0, "level": None, "factors": []}


def test_no_signals_is_zero():
    r = compute_risk(_entity())
    assert r == {"score": 0, "level": None, "factors": []}


def test_young_domain_adds_factor_and_score():
    young = (date.today() - timedelta(days=5)).isoformat()
    r = compute_risk(_entity(metadata={"creation_date": young}))
    assert "dominio_giovane" in r["factors"]
    assert r["score"] == 20


def test_old_domain_does_not_add_factor():
    old = (date.today() - timedelta(days=400)).isoformat()
    r = compute_risk(_entity(metadata={"creation_date": old}))
    assert "dominio_giovane" not in r["factors"]
    assert r["score"] == 0


def test_no_creation_date_key_no_crash_no_factor():
    r = compute_risk(_entity(metadata={}))
    assert "dominio_giovane" not in r["factors"]
    assert r["score"] == 0


def test_malformed_creation_date_no_crash_no_factor():
    r = compute_risk(_entity(metadata={"creation_date": "not-a-date"}))
    assert "dominio_giovane" not in r["factors"]
    assert r["score"] == 0


def test_aggregate_counts_and_overall_level():
    risks = [
        {"score": 100, "level": "critico", "factors": []},
        {"score": 100, "level": "critico", "factors": []},
        {"score": 30, "level": "sospetto", "factors": []},
        {"score": 0, "level": None, "factors": []},
    ]
    agg = aggregate_observation_risk(risks)
    assert agg["counts"] == {"critico": 2, "sospetto": 1, "basso": 0}
    assert agg["overall_level"] == "critico"


def test_aggregate_empty_list():
    agg = aggregate_observation_risk([])
    assert agg["counts"] == {"critico": 0, "sospetto": 0, "basso": 0}
    assert agg["overall_level"] is None


def test_aggregate_overall_level_is_highest_present():
    risks = [{"score": 10, "level": "basso", "factors": []},
             {"score": 40, "level": "sospetto", "factors": []}]
    agg = aggregate_observation_risk(risks)
    assert agg["overall_level"] == "sospetto"
