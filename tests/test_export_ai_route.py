"""GET /e/{id}/export-ai.pdf — export PDF ben formattato + analisi investigativa
LLM on-demand. Il .md resta il formato dati raw/LLM (vedi export.md); questo è
il formato lettura umana (reportlab), verificato via estrazione testo (pypdf)."""
from io import BytesIO

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from pypdf import PdfReader
from app import storage
from app.main import app
from app.models import Entity


class _FakeLLM:
    model_name = "fake-model"

    async def is_available(self):
        return False

    async def generate(self, prompt: str, system: str = "") -> str:
        return ""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "export_ai.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.llm_backend = _FakeLLM()
        yield c


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_export_ai_generates_analysis_when_llm_available(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    with (
        patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=True)),
        patch.object(app.state.llm_backend, "generate", new=AsyncMock(return_value="Analisi generata di test.")),
    ):
        r = client.get(f"/e/{oid}/export-ai.pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    text = _pdf_text(r.content)
    assert "Analisi Investigativa AI" in text
    assert "Analisi generata di test." in text
    assert r.headers["content-disposition"] == f'attachment; filename="poe-{oid}-ai.pdf"'


def test_export_ai_graceful_when_llm_unavailable(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    with patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=False)):
        r = client.get(f"/e/{oid}/export-ai.pdf")
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "1.1.1.1" in text  # raw report content still present
    assert "non disponibile" in text.lower()


def test_export_ai_graceful_on_generate_error(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    with (
        patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=True)),
        patch.object(app.state.llm_backend, "generate", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        r = client.get(f"/e/{oid}/export-ai.pdf")
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "1.1.1.1" in text
    assert "non disponibile" in text.lower()


def test_export_ai_404_on_missing(client):
    assert client.get("/e/99999/export-ai.pdf").status_code == 404


def test_export_ai_headers(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    r = client.get(f"/e/{oid}/export-ai.pdf")
    assert r.headers["content-type"] == "application/pdf"
    assert f"poe-{oid}-ai.pdf" in r.headers["content-disposition"]


def test_detail_page_shows_both_raw_and_ai_export_links(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/export.md" in r.text
    assert f"/e/{oid}/export-ai.pdf" in r.text
    assert "export-dropdown" in r.text
    assert "export-menu" in r.text
    assert "RAW" in r.text
    assert "RAW — Dati — .md" in r.text
    assert "AI — Analisi — .pdf" in r.text
