"""Rendering test per il tooltip del badge di rischio in _macros.html: verifica che
conteggio fonti + freschezza feed reputation (Piece 1) compaiano nel testo del
tooltip di rischio — la reputation non ha più un badge separato, confluisce nel
tooltip del rischio (v0.6.2, badge lettera unico)."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"


def _render_entities(**kwargs):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    tpl = env.from_string(
        '{% import "_macros.html" as m %}{{ m.render_entities(**kwargs) }}'
    )
    return tpl.render(kwargs=kwargs)


def test_reputation_tooltip_shows_source_count_and_freshness():
    grouped = {
        "domain": [
            {
                "value": "evil-example.test",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox", "urlhaus"],
                        "threat": "Cobalt Strike",
                        "reference": "http://ref",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                },
            }
        ]
    }
    risk_by_value = {
        "evil-example.test": {"score": 100, "level": "critico", "factors": ["reputation:threatfox,urlhaus"]},
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value)
    assert "2 fonti" in html
    assert "2026-01-01" in html


def test_reputation_tooltip_singular_source_no_regression():
    grouped = {
        "domain": [
            {
                "value": "evil-example.test",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox"],
                        "threat": None,
                        "reference": None,
                        "updated_at": None,
                    }
                },
            }
        ]
    }
    risk_by_value = {
        "evil-example.test": {"score": 100, "level": "critico", "factors": ["reputation:threatfox"]},
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value)
    assert "1 fonte" in html
    assert "risk-letter-critico" in html


def test_risk_badge_humanizes_dominio_giovane_factor():
    """Piece 2: _humanize_factor già prevede il branch dominio_giovane (commit 893b14b)
    — verifica che renderizzi correttamente con un factor reale. Livello 'sospetto'
    (non 'basso'): dalla v0.6.2 'basso' non mostra più badge (rumore, non segnale)."""
    grouped = {
        "domain": [
            {"value": "young-example.test", "metadata": {}},
        ]
    }
    risk_by_value = {
        "young-example.test": {"score": 30, "level": "sospetto", "factors": ["dominio_giovane"]},
    }
    html = _render_entities(
        grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value
    )
    assert "risk-letter-sospetto" in html
    assert "dominio registrato di recente" in html


def test_basso_level_shows_no_risk_badge():
    """v0.6.2: 'basso' è il livello di default/comune — mostrarlo come badge
    sarebbe rumore, non segnale. Nessun badge per questo livello."""
    grouped = {
        "domain": [
            {"value": "young-example.test", "metadata": {}},
        ]
    }
    risk_by_value = {
        "young-example.test": {"score": 20, "level": "basso", "factors": ["dominio_giovane"]},
    }
    html = _render_entities(
        grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value
    )
    assert "risk-letter" not in html


def test_reputation_shows_dedicated_source_block_in_expansion():
    """L'Operatore vuole, nel pannello espandibile, TUTTI i dati da cui è stata
    derivata la classificazione malevolo/critico — non solo il tooltip del
    badge. Un source_block dedicato (stesso pattern di geo/RDAP/WHOIS: vista
    formattata + raw on demand) copre entrambi con la stessa infrastruttura."""
    grouped = {
        "ipv4": [
            {
                "value": "9.9.9.9",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox", "urlhaus"],
                        "threat": "Cobalt Strike",
                        "reference": "http://ref/9.9.9.9",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                },
            }
        ]
    }
    risk_by_value = {
        "9.9.9.9": {"score": 100, "level": "critico", "factors": ["reputation:threatfox,urlhaus"]},
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value)
    assert "Reputation feed" in html
    assert "threatfox, urlhaus" in html
    assert "Cobalt Strike" in html
    assert "http://ref/9.9.9.9" in html
    assert "2026-01-01" in html
    assert '<a href="http://ref/9.9.9.9"' in html


def test_no_reputation_source_block_when_clean():
    grouped = {"ipv4": [{"value": "1.1.1.1", "metadata": {}}]}
    html = _render_entities(grouped=grouped, observation_id=1, total=1)
    assert "Reputation feed" not in html


def test_reputation_shows_one_source_block_per_hit_with_own_link():
    """Quando l'enrichment ha il dettaglio per-fonte ('hits'), l'espansione
    mostra un source_block per fonte — non un'unica riga aggregata — ognuno
    col proprio riferimento cliccabile e la propria data."""
    grouped = {
        "ipv4": [
            {
                "value": "9.9.9.9",
                "metadata": {
                    "reputation": {
                        "malicious": True,
                        "sources": ["threatfox", "urlhaus"],
                        "threat": "Cobalt Strike",
                        "reference": "http://tf/ref",
                        "updated_at": "2026-01-01T00:00:00",
                        "hits": [
                            {"source": "threatfox", "threat": "Cobalt Strike",
                             "reference": "http://tf/ref", "updated_at": "2026-01-01T00:00:00"},
                            {"source": "urlhaus", "threat": "Emotet",
                             "reference": "http://uh/ref", "updated_at": "2025-06-01T00:00:00"},
                        ],
                    }
                },
            }
        ]
    }
    risk_by_value = {
        "9.9.9.9": {"score": 100, "level": "critico", "factors": ["reputation:threatfox,urlhaus"]},
    }
    html = _render_entities(grouped=grouped, observation_id=1, total=1, risk_by_value=risk_by_value)
    assert "Reputation: threatfox" in html
    assert "Reputation: urlhaus" in html
    assert "Cobalt Strike" in html
    assert "Emotet" in html
    assert '<a href="http://tf/ref"' in html
    assert '<a href="http://uh/ref"' in html
    assert "2026-01-01" in html
    assert "2025-06-01" in html
    # Niente più riga aggregata "Reputation feed" quando i hit sono disponibili
    assert "Reputation feed" not in html
