"""Test per il badge di affidabilità (LOW/MEDIUM/HIGH/CRITICAL) in _macros.html: il 4° livello
CRITICAL è derivato a display-time (non è un valore stored di Entity.confidence)
quando l'estrazione è high-confidence E la reputation è corroborata da 2+ fonti
indipendenti — coerente col principio "confidence ≠ risk ≠ affidabilità"."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"


def _render_entities(**kwargs):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    tpl = env.from_string(
        '{% import "_macros.html" as m %}{{ m.render_entities(**kwargs) }}'
    )
    return tpl.render(kwargs=kwargs)


def test_high_confidence_upgrades_to_critical_with_multi_source_reputation():
    grouped = {
        "ipv4": [
            {
                "value": "9.9.9.9",
                "confidence": "high",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox", "urlhaus"],
                    }
                },
            }
        ]
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "conf-critical" in html
    assert ">CRITICAL<" in html   # badge a parola intera (non più la lettera "C")
    assert "conf-high" not in html


def test_high_confidence_single_source_reputation_stays_high():
    """Una sola fonte non basta a corroborare: resta HIGH, non sale a CRITICAL."""
    grouped = {
        "ipv4": [
            {
                "value": "9.9.9.9",
                "confidence": "high",
                "metadata": {
                    "reputation": {"malicious": True, "sources": ["threatfox"]}
                },
            }
        ]
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "conf-high" in html
    assert "conf-critical" not in html


def test_high_confidence_without_reputation_stays_high():
    grouped = {"ipv4": [{"value": "1.1.1.1", "confidence": "high", "metadata": {}}]}
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "conf-high" in html
    assert "conf-critical" not in html


def test_medium_confidence_with_multi_source_reputation_stays_medium():
    """Il boost a CRITICAL richiede confidence high in partenza, non basta la
    reputation corroborata da sola — altrimenti si confonderebbe di nuovo con
    il badge di rischio (stesso errore che ha causato il redesign)."""
    grouped = {
        "ipv4": [
            {
                "value": "9.9.9.9",
                "confidence": "medium",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox", "urlhaus"],
                    }
                },
            }
        ]
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "conf-medium" in html
    assert "conf-critical" not in html


def test_low_confidence_unaffected():
    grouped = {"domain": [{"value": "x.com", "confidence": "low", "metadata": {}}]}
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "conf-low" in html
    assert "conf-critical" not in html
