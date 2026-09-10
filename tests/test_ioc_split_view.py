"""Vista split card IOC: pannello espanso a 2 colonne (info tool | Analisi AI)
separate da uno splitter centrale trascinabile."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "split.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_panel_has_three_split_children(client):
    """La card espansa ha le due colonne + lo splitter centrale."""
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    html = client.get(f"/e/{oid}").text
    assert 'class="panel-col-tools"' in html
    assert 'class="panel-splitter"' in html
    assert 'class="panel-col-ai"' in html


def test_splitter_is_accessible_separator(client):
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    html = client.get(f"/e/{oid}").text
    assert 'role="separator"' in html
    assert 'aria-orientation="vertical"' in html
    assert 'aria-label="Ridimensiona pannelli"' in html


def test_ai_wrapper_inside_ai_column(client):
    """L'Analisi AI vive nella colonna destra; le fonti tool nella sinistra."""
    oid = storage.save_observation("x", [Entity("domain", "example.com")])
    html = client.get(f"/e/{oid}").text
    ai_col = html.index('class="panel-col-ai"')
    ai_wrap = html.index('class="ai-wrapper"')
    tools_col = html.index('class="panel-col-tools"')
    sources = html.index('class="sources-wrapper"')
    assert tools_col < sources < ai_col < ai_wrap
