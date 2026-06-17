# POE-Home/agents/tools.py
"""Tool generali per l'agente POE. Ogni tool ritorna SEMPRE una stringa
(JSON o messaggio d'errore descrittivo) — mai eccezioni non gestite."""
import json
import os
import sys
import time

import httpx

# Citta' di casa dell'utente — fallback finale se ogni rilevamento fallisce.
_HOME_CITY = "Meda"


def _detect_city_corelocation(fix_timeout: float = 6.0,
                              geocode_timeout: float = 4.0) -> str | None:
    """Posizione via CoreLocation macOS (WiFi positioning, precisione ~strada).

    Richiede il permesso Localizzazione per l'app host (Terminal) in
    Impostazioni > Privacy. Offline usa l'ultima posizione in cache del
    sistema, se presente. Ritorna None su permesso negato/timeout/errore.
    """
    try:
        from CoreLocation import CLGeocoder, CLLocationManager
        from Foundation import NSDate, NSRunLoop

        def _pump(seconds: float, done) -> None:
            deadline = time.time() + seconds
            while time.time() < deadline and not done():
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.15)
                )

        mgr = CLLocationManager.alloc().init()
        mgr.requestWhenInUseAuthorization()
        mgr.startUpdatingLocation()
        _pump(fix_timeout, lambda: mgr.location() is not None)
        loc = mgr.location()
        mgr.stopUpdatingLocation()
        if loc is None:
            return None

        result: dict = {}

        def _handler(placemarks, error):
            if placemarks and len(placemarks) and placemarks[0].locality():
                result["city"] = str(placemarks[0].locality())
            result["done"] = True

        CLGeocoder.alloc().init().reverseGeocodeLocation_completionHandler_(
            loc, _handler
        )
        _pump(geocode_timeout, lambda: "done" in result)
        return result.get("city")
    except Exception:
        return None


def _detect_city_ip() -> str | None:
    """Geolocalizzazione IP (ip-api.com, no key). Precisione ~provider NAT."""
    try:
        r = httpx.get(
            "http://ip-api.com/json/",
            params={"fields": "status,city"},
            timeout=5,
        )
        data = r.json()
        if data.get("status") == "success" and data.get("city"):
            return data["city"]
    except Exception:
        pass
    return None


def _detect_city() -> str:
    """Catena: CoreLocation (preciso) -> IP (approssimato) -> citta' di casa."""
    city = _detect_city_corelocation()
    if city:
        print(f"[POE] Posizione: {city} (fonte: CoreLocation)")
        return city
    city = _detect_city_ip()
    if city:
        print(f"[POE] Posizione: {city} (fonte: IP, ~provider)")
        return city
    print(f"[POE] Posizione: {_HOME_CITY} (fallback casa, rilevamento fallito)")
    return _HOME_CITY


# Posizione corrente dell'utente, risolta una volta all'avvio del server.
# Sotto pytest (o POE_GEO=off) si salta il rilevamento: niente chiamate di
# rete o prompt permessi macOS durante i test.
if "pytest" in sys.modules or os.environ.get("POE_GEO") == "off":
    POE_CITY = _HOME_CITY
else:
    POE_CITY = _detect_city()


def get_weather(city: str = POE_CITY) -> str:
    """Ottiene il meteo attuale per una citta'.

    Args:
        city: Nome della citta'. Se non specificata usa la citta' dell'utente.

    Returns:
        Stringa JSON con temperatura, descrizione, vento e umidita',
        oppure un messaggio di errore descrittivo.
    """
    try:
        resp = httpx.get(
            f"https://wttr.in/{city}",
            params={"format": "j1", "lang": "it"},
            timeout=10,
        )
        resp.raise_for_status()
        cur = resp.json()["current_condition"][0]
        desc_entries = cur.get("lang_it") or cur.get("weatherDesc") or [{"value": ""}]
        return json.dumps({
            "citta": city,
            "temperatura_c": cur["temp_C"],
            "percepita_c": cur["FeelsLikeC"],
            "descrizione": desc_entries[0]["value"],
            "vento_kmh": cur["windspeedKmph"],
            "umidita_pct": cur["humidity"],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Errore meteo: impossibile recuperare i dati per {city} ({e})"


def get_system_status() -> str:
    """Stato di POE e del sistema: usalo per domande su te stesso, sul computer
    o sulla posizione (es. 'come stai?', 'quanta RAM hai?', 'dove sono?',
    'che strumenti hai?', 'da quanto sei attivo?').

    Returns:
        Stringa JSON compatta con stato, uptime, RAM/CPU/disco, posizione,
        meteo, numero di richieste e tool disponibili. Mai eccezioni.
    """
    try:
        resp = httpx.get("http://127.0.0.1:8000/status", timeout=5)
        resp.raise_for_status()
        s = resp.json()
        sis, poe, mod = s["sistema"], s["poe"], s.get("modello", {})
        pos = s.get("posizione", {})
        return json.dumps({
            "stato": poe["stato"],
            "attivo_da": poe["uptime"],
            "ram_libera_gb": sis.get("ram_libera_gb"),
            "cpu_pct": sis.get("cpu_pct"),
            "disco_libero_gb": sis.get("disco_libero_gb"),
            "batteria": sis.get("batteria"),
            "rete": sis.get("rete"),
            "posizione": pos.get("citta"),
            "meteo": pos.get("meteo"),
            "richieste_servite": mod.get("richieste"),
            "tool_disponibili": [t["nome"] for t in s.get("tools", [])],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Errore stato: impossibile leggere lo stato del sistema ({e})"
