"""Task 7: estrazione org/address on-demand via /e/{id}/extract-ai."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "extract.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.llm_backend = MagicMock()
        app.state.llm_backend.is_available = AsyncMock(return_value=True)
        app.state.llm_extractor = MagicMock()
        app.state.llm_extractor.async_extract = AsyncMock(return_value=[
            Entity("org_name", "ACME Spa", confidence="low", metadata={"extractor": "llm"}),
        ])
        yield c


def test_extract_ai_adds_org(client):
    obs_id = storage.save_observation("ACME Spa, Milano", [])
    r = client.post(f"/e/{obs_id}/extract-ai")
    assert r.status_code == 200
    assert "ACME Spa" in r.text
    vals = [e["value"] for e in storage.get_by_id(obs_id)["entities"]]
    assert "ACME Spa" in vals


def test_extract_ai_dedup(client):
    obs_id = storage.save_observation("ACME Spa", [Entity("org_name", "ACME Spa")])
    client.post(f"/e/{obs_id}/extract-ai")
    orgs = [e for e in storage.get_by_id(obs_id)["entities"] if e["value"] == "ACME Spa"]
    assert len(orgs) == 1


def test_extract_ai_from_detail_keeps_export_button(client):
    """Fix 1: cliccando 'LLM Enricher' dalla pagina di dettaglio (/e/{id}), il
    bottone export .md non deve sparire — HX-Current-Url segnala il contesto."""
    obs_id = storage.save_observation("ACME Spa, Milano", [])
    r = client.post(
        f"/e/{obs_id}/extract-ai",
        headers={"HX-Current-Url": f"http://testserver/e/{obs_id}"},
    )
    assert r.status_code == 200
    assert "export-btn" in r.text


def test_extract_ai_from_analyze_has_no_export_button(client):
    """Stesso endpoint chiamato dalla pagina /analyze (nessun header
    HX-Current-Url che punti al dettaglio): comportamento invariato, niente
    bottone export — quella pagina non l'ha mai avuto."""
    obs_id = storage.save_observation("ACME Spa, Milano", [])
    r = client.post(f"/e/{obs_id}/extract-ai")
    assert r.status_code == 200
    assert "export-btn" not in r.text


def test_extract_ai_404(client):
    assert client.post("/e/99999/extract-ai").status_code == 404
