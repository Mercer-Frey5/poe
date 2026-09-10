"""L'hub vocale usa OSINT dall'esterno, senza aprirne l'interfaccia.

La richiesta dell'utente: "voglio che mi cerchi questo IOC, lui fa la ricerca e
mi da' solo l'analisi — tracciata sul modulo, ma senza aprirlo".

Perche' `/api/analyze` non bastava: estraeva le entita' e basta. Niente
arricchimento (nessuna geolocalizzazione, nessun WHOIS) e soprattutto **niente
salvataggio**, quindi la ricerca non lasciava traccia: l'osservazione non
compariva in cronologia, non era ri-apribile, e la volta dopo andava rifatta.

I due comportamenti restano **opt-in**. Il default non cambia, perche' l'endpoint
ha gia' un chiamante — il connettore MCP — che vuole l'estrazione pura, senza
effetti collaterali e senza rete.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "api.db")
    storage.init_db()
    with TestClient(app) as c:
        yield c


# ── il default non cambia ───────────────────────────────────────────────────

def test_senza_flag_non_salva_nulla(client):
    """Il connettore MCP chiama questo endpoint per la sola estrazione: non deve
    ritrovarsi a scrivere osservazioni come effetto collaterale."""
    r = client.post("/api/analyze", json={"text": "scrivimi a mario.rossi@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body.get("observation_id") is None


# ── tracciare: la ricerca lascia un'osservazione ────────────────────────────

def test_con_save_l_osservazione_resta_nel_modulo(client):
    body = client.post("/api/analyze",
                       json={"text": "controlla 8.8.8.8", "save": True}).json()
    assert body["observation_id"] is not None
    salvata = storage.get_by_id(body["observation_id"])
    assert salvata is not None
    assert any(e["value"] == "8.8.8.8" for e in salvata["entities"])


def test_l_osservazione_salvata_e_riapribile(client):
    """"Tracciata sul modulo" vuol dire che l'utente puo' tornarci sopra, non
    solo che e' finita in un log."""
    oid = client.post("/api/analyze",
                      json={"text": "controlla 8.8.8.8", "save": True}).json()["observation_id"]
    assert client.get(f"/e/{oid}").status_code == 200


def test_il_testo_originale_viene_conservato(client):
    testo = "verifica questo indirizzo: 8.8.8.8, grazie"
    oid = client.post("/api/analyze",
                      json={"text": testo, "save": True}).json()["observation_id"]
    assert storage.get_by_id(oid)["raw_input"] == testo


# ── arricchire: l'analisi ha bisogno di piu' dell'estrazione ───────────────

def test_con_enrich_le_entita_portano_la_metadata(client, monkeypatch):
    """Senza arricchimento l'hub riceverebbe "un IP" e nient'altro: non c'e'
    analisi possibile su un valore nudo."""
    async def finto(entities):
        for e in entities:
            if e.type == "ipv4":
                e.metadata.update({"country": "Stati Uniti", "isp": "Google LLC"})
        return entities

    monkeypatch.setattr(app.state.enricher_registry, "enrich_all", finto)
    body = client.post("/api/analyze",
                       json={"text": "controlla 8.8.8.8", "enrich": True}).json()
    ip = next(e for e in body["entities"] if e["type"] == "ipv4")
    assert ip["metadata"]["isp"] == "Google LLC"


def test_enrich_e_save_insieme_persistono_la_metadata(client, monkeypatch):
    async def finto(entities):
        for e in entities:
            e.metadata.update({"country": "Stati Uniti"})
        return entities

    monkeypatch.setattr(app.state.enricher_registry, "enrich_all", finto)
    oid = client.post("/api/analyze", json={
        "text": "controlla 8.8.8.8", "save": True, "enrich": True}).json()["observation_id"]
    salvata = storage.get_by_id(oid)
    ip = next(e for e in salvata["entities"] if e["type"] == "ipv4")
    assert ip["metadata"]["country"] == "Stati Uniti"


def test_un_arricchimento_che_fallisce_non_perde_l_estrazione(client, monkeypatch):
    """La rete puo' mancare: meglio restituire le entita' senza arricchimento che
    far fallire tutta la ricerca."""
    async def rotto(entities):
        raise ConnectionError("ip-api irraggiungibile")

    monkeypatch.setattr(app.state.enricher_registry, "enrich_all", rotto)
    r = client.post("/api/analyze", json={"text": "controlla 8.8.8.8", "enrich": True})
    assert r.status_code == 200
    assert r.json()["count"] >= 1


# ── errori invariati ────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [{"text": "   "}, {}])
def test_input_invalido_resta_errore(client, payload):
    assert client.post("/api/analyze", json=payload).status_code in (400, 422)


def test_niente_da_estrarre_non_e_un_errore(client):
    r = client.post("/api/analyze", json={"text": "buongiorno come va", "save": True})
    assert r.status_code == 200
    assert r.json()["count"] == 0


# ── Lookup live: senza, POE scambia l'assenza di dati per innocenza ─────────
#
# Difetto osservato in uso: a un IP con 156 segnalazioni su AbuseIPDB e un tag
# botnet su OTX, POE ha risposto che "risulta legittimo". Non mentiva: vedeva
# solo geolocalizzazione e WHOIS — "Google Cloud" — perche' l'arricchimento
# copre geo, RDAP e il feed abuse.ch locale, mentre reputazione e minacce
# stanno nei lookup LIVE, che il percorso headless non eseguiva affatto.
#
# E' l'errore piu' pericoloso che questo sistema possa fare: dire "pulito"
# quando la risposta onesta e' "non ho guardato".

def _handler_finto(risultato):
    async def h(valore):
        return risultato
    return h


def test_senza_lookups_non_si_interroga_nessuna_fonte(client, monkeypatch):
    chiamate = []

    async def h(valore):
        chiamate.append(valore)
        return {"ok": True}

    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-shodan", h)
    client.post("/api/analyze", json={"text": "8.8.8.8"})
    assert chiamate == []


def test_con_lookups_le_fonti_vengono_interrogate(client, monkeypatch):
    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-shodan",
                        _handler_finto({"ok": True, "porte": [22]}))
    body = client.post("/api/analyze",
                       json={"text": "8.8.8.8", "lookups": True}).json()
    fonti = body["lookups"]["8.8.8.8"]
    assert fonti["site-shodan"]["porte"] == [22]


def test_i_lookup_vengono_salvati_con_l_osservazione(client, monkeypatch):
    """Cosi' l'analisi che POE riporta in chat e quella che si vede aprendo
    l'osservazione sono la stessa cosa."""
    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-shodan",
                        _handler_finto({"ok": True, "porte": [22]}))
    oid = client.post("/api/analyze", json={
        "text": "8.8.8.8", "save": True, "lookups": True}).json()["observation_id"]
    salvati = storage.get_lookup_results(oid)
    assert salvati["8.8.8.8"]["site-shodan"]["porte"] == [22]


def test_una_fonte_che_esplode_non_perde_le_altre(client, monkeypatch):
    async def rotto(valore):
        raise ConnectionError("giu'")

    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-shodan", rotto)
    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-urlscan-ip",
                        _handler_finto({"ok": True, "found": False}))
    body = client.post("/api/analyze",
                       json={"text": "8.8.8.8", "lookups": True}).json()
    fonti = body["lookups"]["8.8.8.8"]
    assert fonti["site-urlscan-ip"]["ok"] is True
    assert fonti["site-shodan"]["ok"] is False, "il guasto va riportato, non nascosto"


def test_si_dichiara_quali_fonti_sono_state_consultate(client, monkeypatch):
    """Chi legge deve poter distinguere "nessuna minaccia trovata" da "quella
    fonte non e' stata interrogata"."""
    monkeypatch.setitem(main._LOOKUP_HANDLERS, "site-shodan",
                        _handler_finto({"ok": True}))
    body = client.post("/api/analyze",
                       json={"text": "8.8.8.8", "lookups": True}).json()
    assert "site-shodan" in body["lookups"]["8.8.8.8"]


def test_senza_entita_non_si_interroga_nulla(client):
    """Nessun indicatore, nessuna fonte da consultare: non si spreca quota."""
    body = client.post("/api/analyze",
                       json={"text": "buongiorno come va", "lookups": True}).json()
    assert body["count"] == 0
    assert body["lookups"] == {}
