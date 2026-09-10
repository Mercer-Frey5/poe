"""Task 1: report.py — build_markdown_report (parita' + arricchimento) e build_json_report."""
from app.report import build_markdown_report, build_json_report


def _obs(entities=None, kept=False, label=None, synthesis=None):
    obs = {
        "id": 7, "timestamp": "2026-07-05T10:00:00", "raw_input": "test input",
        "entities": entities or [], "kept": kept, "label": label,
    }
    if synthesis:
        obs["synthesis_text"], obs["synthesis_model"] = synthesis
    return obs


# ── build_markdown_report: parita' col formato base esistente ──

def test_md_header_contains_id_when_no_label():
    md = build_markdown_report(_obs())
    assert "# POE — Osservazione #7" in md


def test_md_contains_score_accuracy_kept_state():
    entities = [{"type": "email", "value": "a@b.com", "original": "a@b.com",
                 "confidence": "medium", "metadata": {}}]
    md = build_markdown_report(_obs(entities=entities, kept=True))
    assert "Score:" in md and "Accuratezza media:" in md and "kept" in md


def test_md_high_confidence_annotated():
    entities = [{"type": "phone", "value": "+391234567890", "original": "+391234567890",
                 "confidence": "high", "metadata": {}}]
    md = build_markdown_report(_obs(entities=entities))
    assert "[high]" in md


def test_md_synthesis_section_present_when_saved():
    md = build_markdown_report(_obs(synthesis=("analisi generata", "llama-3.1-8b")))
    assert "## Sintesi Intelligence" in md
    assert "analisi generata" in md


# ── build_markdown_report: arricchimento nuovo ──

def test_md_clean_ioc_no_noise():
    entities = [{"type": "ipv4", "value": "1.1.1.1", "original": "1.1.1.1",
                 "confidence": "medium", "metadata": {}}]
    md = build_markdown_report(_obs(entities=entities))
    assert "1.1.1.1" in md
    assert "rischio" not in md and "malevolo" not in md and "geo:" not in md


def test_md_full_signals_on_one_ioc():
    entities = [{"type": "ipv4", "value": "9.9.9.9", "original": "9.9.9.9",
                 "confidence": "medium",
                 "metadata": {"reputation": {"malicious": True, "sources": ["threatfox"], "threat": "Cobalt Strike"},
                              "country": "US", "city": "Ashburn"}}]
    risk_by_value = {"9.9.9.9": {"score": 100, "level": "critico", "factors": ["reputation:threatfox"]}}
    pivot_info = {"9.9.9.9": {"count": 3, "other_observation_ids": [4, 8]}}
    md = build_markdown_report(_obs(entities=entities), risk_by_value=risk_by_value, pivot_info=pivot_info)
    assert "[rischio: critico]" in md
    assert "⚠ malevolo (threatfox, Cobalt Strike)" in md
    assert "geo: US/Ashburn" in md
    assert "visto in 3 oss." in md and "#4" in md and "#8" in md


def test_md_correlazioni_section_only_when_pivot_present():
    entities = [{"type": "ipv4", "value": "1.1.1.1", "original": "1.1.1.1",
                 "confidence": "medium", "metadata": {}}]
    md_no_pivot = build_markdown_report(_obs(entities=entities))
    assert "## Correlazioni" not in md_no_pivot

    pivot_info = {"1.1.1.1": {"count": 2, "other_observation_ids": [5]}}
    md_with_pivot = build_markdown_report(_obs(entities=entities), pivot_info=pivot_info)
    assert "## Correlazioni" in md_with_pivot
    assert "#5" in md_with_pivot


def test_md_observation_risk_line_only_when_overall_level_set():
    entities = [{"type": "ipv4", "value": "1.1.1.1", "original": "1.1.1.1",
                 "confidence": "medium", "metadata": {}}]
    md_none = build_markdown_report(
        _obs(entities=entities),
        observation_risk={"counts": {"critico": 0, "sospetto": 0, "basso": 0}, "overall_level": None},
    )
    assert "Rischio osservazione" not in md_none

    md_set = build_markdown_report(
        _obs(entities=entities),
        observation_risk={"counts": {"critico": 1, "sospetto": 2, "basso": 0}, "overall_level": "critico"},
    )
    assert "Rischio osservazione: ⚠ 1 critici · 2 sospetti" in md_set


# ── build_json_report ──

def test_json_full_structure():
    entities = [{"type": "ipv4", "value": "9.9.9.9", "original": "9.9.9.9",
                 "confidence": "medium", "metadata": {"country": "US"}}]
    risk_by_value = {"9.9.9.9": {"score": 30, "level": "sospetto", "factors": ["tld_sospetto"]}}
    observation_risk = {"counts": {"critico": 0, "sospetto": 1, "basso": 0}, "overall_level": "sospetto"}
    pivot_info = {"9.9.9.9": {"count": 2, "other_observation_ids": [3]}}

    report = build_json_report(_obs(entities=entities, label="Indagine X"),
                                risk_by_value=risk_by_value, observation_risk=observation_risk,
                                pivot_info=pivot_info)

    assert report["id"] == 7
    assert report["label"] == "Indagine X"
    assert report["risk"]["overall_level"] == "sospetto"
    e = report["entities"][0]
    assert e["value"] == "9.9.9.9"
    assert e["metadata"] == {"country": "US"}
    assert e["risk"]["level"] == "sospetto"
    assert e["pivot"]["count"] == 2
    assert e["pivot"]["other_observation_ids"] == [3]


def test_json_synthesis_null_when_not_saved():
    report = build_json_report(_obs())
    assert report["synthesis"] is None


def test_json_synthesis_present_when_saved():
    report = build_json_report(_obs(synthesis=("testo", "modelX")))
    assert report["synthesis"] == {"text": "testo", "model": "modelX"}


# ── live_results_by_value: il file scaricabile dall'utente deve avere gli
# stessi dati raw (tool live: AbuseIPDB/VirusTotal/Shodan/BGP.HE.net/crt.sh)
# che ha già il LLM — bug reale: scaricando il .md/.json non c'era quasi
# nessun dato, solo un sottoinsieme cherry-picked (geo/registrar/rischio).

def test_md_includes_live_lookup_raw_data():
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium", "metadata": {"country": "United States"}}]
    live_results_by_value = {
        "132.144.1.4": {"AbuseIPDB": {"ok": True, "abuse_score": 0, "usage_type": "Government"}},
    }
    md = build_markdown_report(_obs(entities=entities), live_results_by_value=live_results_by_value)
    assert "AbuseIPDB" in md
    assert "Government" in md


def test_md_includes_full_raw_metadata_not_just_highlights():
    """Anche i campi metadata non presenti nell'highlight sintetico (es. isp,
    org) devono comparire nel raw allegato per entità."""
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium",
                 "metadata": {"country": "United States", "isp": "DoD Network Information Center",
                              "org": "Disa Thunderdome Program Office"}}]
    md = build_markdown_report(_obs(entities=entities))
    assert "DoD Network Information Center" in md
    assert "Disa Thunderdome Program Office" in md


def test_json_includes_live_results_per_entity():
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium", "metadata": {}}]
    live_results_by_value = {
        "132.144.1.4": {"AbuseIPDB": {"ok": True, "abuse_score": 0}},
    }
    report = build_json_report(_obs(entities=entities), live_results_by_value=live_results_by_value)
    assert report["entities"][0]["live_results"] == {"AbuseIPDB": {"ok": True, "abuse_score": 0}}
