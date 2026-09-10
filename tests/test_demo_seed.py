"""demo_seed.py — dati demo per test manuale (POE_DEMO_DATA=1). Seed una
sola volta (skip se il DB ha già osservazioni), per non duplicare a ogni
restart/--reload durante lo sviluppo."""
import pytest
from app import storage
from app.demo_seed import seed_demo_data
from app.risk_scoring import compute_risk


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "demo.db")
    storage.init_db()


def test_seed_demo_data_creates_observations_when_empty(temp_db):
    seed_demo_data()
    obs = storage.get_recent(limit=10)
    assert len(obs) >= 3


def test_seed_demo_data_skips_when_not_empty(temp_db):
    from app.models import Entity
    storage.save_observation("osservazione reale dell'operatore", [Entity("email", "a@b.com")])
    seed_demo_data()
    obs = storage.get_recent(limit=10)
    assert len(obs) == 1  # nessuna demo aggiunta sopra il dato reale


def test_seed_demo_data_covers_malevolo_and_sospetto_risk_tiers(temp_db):
    """Le entità seedate devono attraversare compute_risk esattamente come
    farebbe un'osservazione reale arricchita — verifica che la demo eserciti
    davvero i livelli di rischio, non solo che esista del testo a caso."""
    seed_demo_data()
    obs = storage.get_recent(limit=10)
    all_entities = [e for o in obs for e in o["entities"]]
    levels = {compute_risk(e)["level"] for e in all_entities}
    assert "critico" in levels    # badge "Malevolo" (reputation match)
    assert "sospetto" in levels   # badge "Sospetto" (tld/dominio giovane)


def test_seed_demo_data_covers_critical_confidence_tier(temp_db):
    """Un'entità high-confidence + reputation corroborata da 2+ fonti deve
    esistere, per esercitare il badge affidabilità CRITICAL a display-time."""
    seed_demo_data()
    obs = storage.get_recent(limit=10)
    all_entities = [e for o in obs for e in o["entities"]]
    hit = next(
        e for e in all_entities
        if e.get("confidence") == "high"
        and len((e.get("metadata") or {}).get("reputation", {}).get("sources", [])) >= 2
    )
    assert hit is not None


def test_seed_demo_data_labels_are_marked_as_demo(temp_db):
    seed_demo_data()
    obs = storage.get_recent(limit=10)
    assert all((o.get("label") or "").startswith("[DEMO]") for o in obs)


def test_lifespan_seeds_only_when_env_var_set(tmp_path, monkeypatch):
    """Integrazione: il gate POE_DEMO_DATA è letto nel lifespan reale di
    app.main, non solo nella funzione isolata — di default (env non settato,
    come in tutto il resto della test suite) non deve mai seedare nulla."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "lifespan_off.db")
    monkeypatch.delenv("POE_DEMO_DATA", raising=False)
    from app.main import app
    with TestClient(app, raise_server_exceptions=True):
        pass
    assert storage.get_recent(limit=10) == []


def test_lifespan_seeds_when_env_var_enabled(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "lifespan_on.db")
    monkeypatch.setenv("POE_DEMO_DATA", "1")
    from app.main import app
    with TestClient(app, raise_server_exceptions=True):
        pass
    assert len(storage.get_recent(limit=10)) >= 3
