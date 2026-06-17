# POE-Home/tests/test_tools.py
import json
from unittest.mock import MagicMock, patch

from agents.tools import get_weather


def _wttr_payload():
    return {
        "current_condition": [{
            "temp_C": "18",
            "FeelsLikeC": "17",
            "windspeedKmph": "11",
            "humidity": "63",
            "lang_it": [{"value": "Sereno"}],
            "weatherDesc": [{"value": "Clear"}],
        }]
    }


@patch("agents.tools.httpx.get")
def test_get_weather_success(mock_get):
    resp = MagicMock()
    resp.json.return_value = _wttr_payload()
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    out = json.loads(get_weather("Firenze"))
    assert out["citta"] == "Firenze"
    assert out["temperatura_c"] == "18"
    assert out["descrizione"] == "Sereno"
    assert out["vento_kmh"] == "11"
    assert out["umidita_pct"] == "63"
    args, kwargs = mock_get.call_args
    assert "wttr.in/Firenze" in args[0]
    assert kwargs["timeout"] == 10


@patch("agents.tools.httpx.get")
def test_get_weather_fallback_to_english_desc(mock_get):
    payload = _wttr_payload()
    del payload["current_condition"][0]["lang_it"]
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    out = json.loads(get_weather("Firenze"))
    assert out["descrizione"] == "Clear"


@patch("agents.tools.httpx.get")
def test_get_weather_network_error_returns_message(mock_get):
    mock_get.side_effect = Exception("connection refused")
    out = get_weather("Firenze")
    assert "Errore meteo" in out
    assert "Firenze" in out


# ── Catena rilevamento posizione: CoreLocation -> IP -> citta' di casa ──────

@patch("agents.tools._detect_city_ip")
@patch("agents.tools._detect_city_corelocation")
def test_detect_city_prefers_corelocation(mock_cl, mock_ip):
    mock_cl.return_value = "Meda"
    out = __import__("agents.tools", fromlist=["_detect_city"])._detect_city()
    assert out == "Meda"
    mock_ip.assert_not_called()


@patch("agents.tools._detect_city_ip")
@patch("agents.tools._detect_city_corelocation")
def test_detect_city_falls_back_to_ip(mock_cl, mock_ip):
    mock_cl.return_value = None
    mock_ip.return_value = "Paderno Dugnano"
    out = __import__("agents.tools", fromlist=["_detect_city"])._detect_city()
    assert out == "Paderno Dugnano"


@patch("agents.tools._detect_city_ip")
@patch("agents.tools._detect_city_corelocation")
def test_detect_city_falls_back_to_home(mock_cl, mock_ip):
    mock_cl.return_value = None
    mock_ip.return_value = None
    out = __import__("agents.tools", fromlist=["_detect_city"])._detect_city()
    assert out == "Meda"


# ── get_system_status ──────────────────────────────────────────────────────

def _status_payload():
    return {
        "poe": {"stato": "operativo", "uptime": "1h 02m"},
        "posizione": {"citta": "Meda", "meteo": "18°C, coperto"},
        "sistema": {"ram_libera_gb": 3.2, "cpu_pct": 41, "disco_libero_gb": 120.5,
                    "batteria": "80% su batteria", "rete": "online"},
        "modello": {"richieste": 7},
        "tools": [{"nome": "meteo", "stato": "ok"}, {"nome": "web search", "stato": "ok"}],
    }


def test_get_system_status_success(monkeypatch):
    from agents import tools as tmod
    resp = MagicMock()
    resp.json.return_value = _status_payload()
    resp.raise_for_status.return_value = None
    monkeypatch.setattr(tmod.httpx, "get", lambda *a, **k: resp)

    out = json.loads(tmod.get_system_status())
    assert out["stato"] == "operativo"
    assert out["posizione"] == "Meda"
    assert out["meteo"] == "18°C, coperto"
    assert out["ram_libera_gb"] == 3.2
    assert out["richieste_servite"] == 7
    assert "meteo" in out["tool_disponibili"]


def test_get_system_status_network_error(monkeypatch):
    from agents import tools as tmod
    def boom(*a, **k):
        raise Exception("connection refused")
    monkeypatch.setattr(tmod.httpx, "get", boom)
    out = tmod.get_system_status()
    assert "Errore stato" in out
