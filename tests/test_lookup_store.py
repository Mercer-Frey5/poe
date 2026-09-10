"""I risultati dei lookup live sopravvivono alla richiesta che li ha prodotti.

Prima vivevano in un dict globale in RAM (`_LIVE_LOOKUP_CACHE`), e questo aveva
tre conseguenze, tutte invisibili finche' non le si cerca:

1. **La sintesi investigativa vedeva zero dati live** se l'utente non aveva
   prima espanso a mano le card degli IOC. Il pannello e' un bottone
   indipendente: cliccarlo per primo — il modo normale di usarlo — produceva
   un'analisi basata sul solo enrichment deterministico.
2. **Gli export dopo un riavvio erano poveri**: `.md`, `.json` e il PDF
   attingevano alla stessa cache volatile, quindi dichiaravano "solo enrichment
   automatico" anche per osservazioni su cui i lookup erano stati fatti.
3. **Ogni riapertura di una card ri-colpiva le API esterne**, bruciando quota
   per ridisegnare dati gia' ottenuti.

Persistere risolve tutti e tre. Ma introduce un dovere nuovo: questi risultati
contengono PII (account trovati, email, operatore telefonico, dati anagrafici
decodificati da un codice fiscale). Cancellare un'osservazione deve cancellare
anche loro — altrimenti la PII sopravvive a un'eliminazione chiesta proprio per
liberarsene.
"""
from __future__ import annotations

import pytest

from app import storage
from app.models import Entity


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "lookup.db")
    storage.init_db()


def _osservazione(valore: str = "8.8.8.8") -> int:
    return storage.save_observation("testo", [Entity("ipv4", valore)])


# ── salvataggio e rilettura ─────────────────────────────────────────────────

def test_salva_e_rilegge():
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8",
                               {"ok": True, "score": 0})
    out = storage.get_lookup_results(oid)
    assert out == {"8.8.8.8": {"site-abuseipdb": {"ok": True, "score": 0}}}


def test_rilettura_filtrata_per_entita():
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True})
    storage.save_lookup_result(oid, "site-gravatar", "a@b.com", {"ok": True})
    assert set(storage.get_lookup_results(oid, "8.8.8.8")) == {"8.8.8.8"}


def test_piu_fonti_per_la_stessa_entita():
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True})
    storage.save_lookup_result(oid, "site-shodan", "8.8.8.8", {"ok": True, "porte": [53]})
    assert set(storage.get_lookup_results(oid)["8.8.8.8"]) == {"site-abuseipdb", "site-shodan"}


def test_un_nuovo_risultato_sostituisce_il_precedente():
    """Rieseguire un lookup aggiorna la riga invece di accumularne due: la card
    deve mostrare l'ultimo esito, non il primo."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True, "score": 0})
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True, "score": 87})
    assert storage.get_lookup_results(oid)["8.8.8.8"]["site-abuseipdb"]["score"] == 87


def test_osservazione_senza_lookup():
    assert storage.get_lookup_results(_osservazione()) == {}


def test_i_risultati_non_sconfinano_fra_osservazioni():
    a, b = _osservazione(), _osservazione("1.1.1.1")
    storage.save_lookup_result(a, "site-abuseipdb", "8.8.8.8", {"ok": True})
    assert storage.get_lookup_results(b) == {}


def test_anche_gli_esiti_negativi_si_salvano():
    """"Nessun dato su questo IOC" e' un'informazione per l'analista e per l'AI:
    evita di rilanciare il lookup e dice che la fonte e' stata guardata."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-shodan", "8.8.8.8",
                               {"ok": False, "error": "quota esaurita"})
    assert storage.get_lookup_results(oid)["8.8.8.8"]["site-shodan"]["ok"] is False


# ── sopravvivenza al riavvio ────────────────────────────────────────────────

def test_sopravvive_a_una_nuova_connessione():
    """Il punto di tutto: prima dell'introduzione della tabella, un riavvio del
    server azzerava ogni lookup fatto."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True, "score": 12})
    storage.init_db()          # come un riavvio: riapre e rimigra
    assert storage.get_lookup_results(oid)["8.8.8.8"]["site-abuseipdb"]["score"] == 12


def test_migrazione_su_db_preesistente():
    """La tabella va aggiunta a DB gia' popolati senza perderne il contenuto."""
    oid = _osservazione()
    storage.init_db()
    storage.init_db()
    assert storage.get_by_id(oid) is not None
    assert storage.get_lookup_results(oid) == {}


# ── PII: cancellare vuol dire cancellare ───────────────────────────────────

def test_cancellare_l_osservazione_cancella_i_lookup():
    """I risultati contengono PII. Se sopravvivessero all'eliminazione
    dell'osservazione resterebbero in un DB da cui l'utente credeva di averli
    tolti — e finirebbero in un backup o in un commit."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-holehe", "a@b.com", {"ok": True, "siti": ["x"]})
    storage.delete_observation(oid)
    assert storage.get_lookup_results(oid) == {}
    assert storage.count_lookup_results() == 0


def test_reset_db_svuota_anche_i_lookup():
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-holehe", "a@b.com", {"ok": True})
    storage.reset_db()
    assert storage.count_lookup_results() == 0


# ── robustezza ──────────────────────────────────────────────────────────────

def test_un_risultato_non_serializzabile_non_fa_cadere_il_lookup():
    """Salvare e' un effetto collaterale del lookup: se fallisce, l'utente deve
    comunque vedere il risultato a schermo."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-x", "8.8.8.8", {"ok": True, "bad": {1, 2}})
    assert storage.get_lookup_results(oid) == {}


def test_json_corrotto_a_riposo_viene_saltato():
    """Una riga illeggibile non deve impedire di leggere le altre."""
    oid = _osservazione()
    storage.save_lookup_result(oid, "site-ok", "8.8.8.8", {"ok": True})
    with storage._connect() as conn:
        conn.execute(
            "INSERT INTO lookup_results (observation_id, resource_id, entity_value,"
            " fetched_at, ok, result_json) VALUES (?,?,?,?,?,?)",
            (oid, "site-rotto", "8.8.8.8", "2026-09-01T00:00:00+00:00", 1, "{non json"),
        )
    out = storage.get_lookup_results(oid)
    assert "site-ok" in out["8.8.8.8"]
    assert "site-rotto" not in out["8.8.8.8"]


# ── Il difetto che la persistenza risolve ───────────────────────────────────

def test_la_sintesi_vede_i_lookup_senza_aprire_nessuna_card(monkeypatch):
    """Il caso d'uso normale, che prima produceva un'analisi cieca.

    Il pannello "Genera sintesi investigativa" e' un bottone indipendente
    dall'espansione degli IOC. Chi lo clicca per primo — senza aver aperto
    nessuna card in questa sessione — con la cache in RAM otteneva `{}` per
    ogni entita', e l'AI ragionava sul solo enrichment deterministico senza che
    nulla lo segnalasse.
    """
    from app.main import _LIVE_LOOKUP_CACHE, _build_synthesis_prompt

    oid = _osservazione("132.144.1.4")
    storage.save_lookup_result(oid, "site-abuseipdb", "132.144.1.4",
                               {"ok": True, "abuse_score": 0, "usage_type": "Government"})
    _LIVE_LOOKUP_CACHE.clear()      # nessuna card aperta in questa sessione

    entities = [{"type": "ipv4", "value": "132.144.1.4",
                 "confidence": "medium", "metadata": {}}]
    user, _ = _build_synthesis_prompt("raw", entities, observation_id=oid)
    assert "AbuseIPDB" in user
    assert "Government" in user


def test_l_analisi_per_ioc_vede_i_lookup_di_una_sessione_precedente():
    """Stesso principio sull'analisi del singolo IOC: un lookup fatto ieri deve
    entrare nell'analisi di oggi."""
    from app.main import _LIVE_LOOKUP_CACHE, _cached_live_results_for

    oid = _osservazione()
    storage.save_lookup_result(oid, "site-shodan", "8.8.8.8",
                               {"ok": True, "porte": [53, 443]})
    _LIVE_LOOKUP_CACHE.clear()      # come dopo un riavvio del server
    assert _cached_live_results_for(oid, "8.8.8.8")["site-shodan"]["porte"] == [53, 443]


def test_il_risultato_appena_ottenuto_ha_la_precedenza():
    """La cache in RAM contiene il dato piu' fresco: se una fonte e' presente in
    entrambi i livelli, vince quella appena scaricata."""
    from app.main import _LIVE_LOOKUP_CACHE, _cached_live_results_for

    oid = _osservazione()
    storage.save_lookup_result(oid, "site-abuseipdb", "8.8.8.8", {"ok": True, "score": 0})
    _LIVE_LOOKUP_CACHE.clear()
    _LIVE_LOOKUP_CACHE[(oid, "site-abuseipdb", "8.8.8.8")] = {"ok": True, "score": 99}
    try:
        assert _cached_live_results_for(oid, "8.8.8.8")["site-abuseipdb"]["score"] == 99
    finally:
        _LIVE_LOOKUP_CACHE.clear()
