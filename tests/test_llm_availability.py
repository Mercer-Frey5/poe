"""Quali motori AI puo' davvero usare questa macchina.

POE nasceva tarato su un Mac M1: il backend predefinito era MLX, scritto nel
codice, su qualunque hardware. Chi scaricava il progetto su Windows o Linux
otteneva un avviso, un ripiego silenzioso su Ollama, e — se Ollama non c'era —
un errore incomprensibile al primo clic su una funzione AI. Il difetto non era
il ripiego: era che nessuno diceva cosa stesse succedendo.

Qui si guarda la macchina e si risponde a due domande, separatamente:

- **cosa e' utilizzabile**, per scegliere un default sensato invece di uno fisso;
- **perche' il resto non lo e'**, perche' "MLX non disponibile" e' inutile mentre
  "MLX richiede Apple Silicon, qui l'architettura e' x86_64" dice cosa fare.

Nessuna sonda solleva e nessuna e' obbligatoria: un motore che non si riesce a
verificare risulta non disponibile, e la pipeline deterministica — che e' il
cuore di POE — funziona comunque senza alcun LLM.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.llm.availability import Disponibilita, backend_predefinito, rileva


def _finto(*, apple=False, ollama=False, claude=False,
           openai=False) -> Disponibilita:
    """Tutte e quattro le sonde iniettate: se una restasse quella vera,
    l'esito del test dipenderebbe dall'ambiente di chi lo lancia."""
    return rileva(
        apple_silicon=lambda: apple,
        ollama_attivo=lambda: ollama,
        claude_installato=lambda: claude,
        openai_configurato=lambda: openai,
    )


# ── cosa e' utilizzabile ────────────────────────────────────────────────────

def test_su_apple_silicon_mlx_e_utilizzabile():
    assert _finto(apple=True).usabile("mlx") is True


def test_fuori_da_apple_silicon_mlx_non_lo_e():
    assert _finto(apple=False).usabile("mlx") is False


def test_ollama_dipende_dal_servizio_non_dal_sistema():
    """Ollama gira ovunque, ma solo se e' avviato: e' un servizio, non una
    libreria."""
    assert _finto(apple=False, ollama=True).usabile("ollama") is True
    assert _finto(apple=True, ollama=False).usabile("ollama") is False


def test_claude_dipende_dal_binario():
    assert _finto(claude=True).usabile("claude") is True
    assert _finto(claude=False).usabile("claude") is False


def test_un_backend_sconosciuto_non_e_utilizzabile():
    assert _finto(apple=True).usabile("banana") is False


# ── perche' no: il motivo serve piu' del verdetto ──────────────────────────

def test_dice_perche_mlx_non_va():
    assert "apple silicon" in _finto(apple=False).motivo("mlx").lower()


def test_dice_come_rimediare_a_ollama_spento():
    motivo = _finto(ollama=False).motivo("ollama").lower()
    assert "ollama" in motivo
    assert any(p in motivo for p in ("avvia", "installa", "serve"))


def test_dice_come_rimediare_a_claude_assente():
    assert "claude" in _finto(claude=False).motivo("claude").lower()


def test_un_motore_utilizzabile_non_ha_un_motivo_contrario():
    assert _finto(apple=True).motivo("mlx") == ""


# ── il default: scelto, non cablato ────────────────────────────────────────

def test_su_apple_silicon_si_preferisce_il_locale_nativo():
    assert backend_predefinito(_finto(apple=True, ollama=True, claude=True)) == "mlx"


def test_altrove_si_preferisce_ollama():
    """Gira su qualunque hardware e i dati restano sulla macchina: e' il default
    giusto per chi non ha un Mac."""
    assert backend_predefinito(_finto(apple=False, ollama=True, claude=True)) == "ollama"


def test_senza_locale_si_ripiega_su_claude():
    assert backend_predefinito(_finto(apple=False, ollama=False, claude=True)) == "claude"


def test_il_locale_batte_il_cloud_quando_c_e():
    """Privacy prima della comodita': se un motore locale e' disponibile, i dati
    non escono dalla macchina."""
    assert backend_predefinito(_finto(apple=False, ollama=True, claude=True)) == "ollama"


def test_senza_nessun_motore_non_si_inventa_nulla():
    """La pipeline deterministica e' il cuore di POE e non usa LLM: meglio
    dichiarare che non c'e' motore AI, che fingerne uno che fallira'."""
    assert backend_predefinito(_finto()) is None


# ── la scelta esplicita dell'utente ────────────────────────────────────────

def test_la_scelta_dell_utente_ha_la_precedenza():
    d = _finto(apple=True, ollama=True, claude=True)
    assert backend_predefinito(d, preferito="claude") == "claude"


def test_una_scelta_impossibile_non_viene_imposta():
    """Chiedere MLX su un PC senza Apple Silicon non puo' funzionare: meglio un
    motore che va, che uno che non partira'."""
    assert backend_predefinito(_finto(apple=False, ollama=True), preferito="mlx") == "ollama"


def test_una_scelta_ignota_viene_ignorata():
    assert backend_predefinito(_finto(apple=True), preferito="banana") == "mlx"


# ── forma, per la UI e per /api/status ─────────────────────────────────────

def test_lo_stato_e_ispezionabile_per_intero():
    stato = _finto(apple=False, ollama=True, claude=False).as_dict()
    assert set(stato) == {"mlx", "ollama", "openai", "claude"}
    assert stato["ollama"]["usabile"] is True
    assert stato["mlx"]["usabile"] is False and stato["mlx"]["motivo"]


def test_elenca_i_motori_pronti():
    assert _finto(apple=True, claude=True).pronti() == ["mlx", "claude"]


# ── le sonde vere non devono mai far cadere l'avvio ────────────────────────

def test_una_sonda_che_esplode_vale_non_disponibile():
    def rotta():
        raise OSError("qualcosa e' andato storto")

    d = rileva(apple_silicon=rotta, ollama_attivo=rotta,
               claude_installato=rotta, openai_configurato=rotta)
    assert d.pronti() == []
    assert backend_predefinito(d) is None


def test_le_sonde_reali_rispondono_senza_sollevare():
    """Girano all'avvio su hardware sconosciuto: qualunque cosa trovino, devono
    tornare un booleano."""
    from app.llm import availability

    for sonda in (availability.e_apple_silicon,
                  availability.ollama_attivo,
                  availability.claude_installato):
        assert isinstance(sonda(), bool)


@pytest.mark.parametrize("macchina, sistema, atteso", [
    ("arm64", "Darwin", True),
    ("x86_64", "Darwin", False),     # Mac Intel: niente MLX
    ("arm64", "Linux", False),       # ARM ma non Apple
    ("x86_64", "Linux", False),
])
def test_apple_silicon_riconosciuto_correttamente(macchina, sistema, atteso):
    from app.llm import availability

    with patch("platform.machine", return_value=macchina), \
         patch("platform.system", return_value=sistema):
        assert availability.e_apple_silicon() is atteso


# ── il motore compatibile OpenAI ───────────────────────────────────────────
#
# Copre LM Studio, llama.cpp, vLLM, LocalAI, OpenRouter e chiunque altro parli
# lo stesso protocollo: fra loro cambia l'indirizzo, non l'API.

def test_openai_e_utilizzabile_se_configurato():
    assert _finto(openai=True).usabile("openai") is True
    assert _finto(openai=False).usabile("openai") is False


def test_dice_come_configurare_openai():
    motivo = _finto(openai=False).motivo("openai")
    assert "POE_OPENAI_BASE_URL" in motivo


def test_openai_viene_dopo_i_locali_ma_prima_del_cloud():
    """Puo' puntare a un server locale come a uno remoto: sta in mezzo, dopo i
    motori certamente locali e prima di quello certamente cloud."""
    assert backend_predefinito(_finto(ollama=True, openai=True)) == "ollama"
    assert backend_predefinito(_finto(openai=True, claude=True)) == "openai"


def test_la_sonda_openai_guarda_l_ambiente(monkeypatch):
    from app.llm import availability

    monkeypatch.delenv("POE_OPENAI_BASE_URL", raising=False)
    assert availability.openai_configurato() is False
    monkeypatch.setenv("POE_OPENAI_BASE_URL", "http://localhost:1234/v1")
    assert availability.openai_configurato() is True


# ── e_locale: l'indirizzo tiene i dati sulla macchina, o li manda fuori? ────
#
# Il backend compatibile OpenAI puo' puntare a LM Studio sulla stessa macchina
# o a OpenRouter dall'altra parte del mondo: stesso protocollo, privacy opposta.
# Senza questa distinzione POE lo classificava sempre "locale", anche quando
# l'utente lo puntava esplicitamente a un servizio cloud — l'esatto contrario
# di quello che la status bar promette di mostrare.

def test_localhost_e_locale():
    from app.llm.availability import e_locale
    assert e_locale("http://localhost:1234/v1") is True


def test_loopback_ip_e_locale():
    from app.llm.availability import e_locale
    assert e_locale("http://127.0.0.1:1234/v1") is True


def test_rete_privata_e_locale():
    """LAN casalinga o aziendale: i dati restano dentro il perimetro, non su
    Internet pubblico."""
    from app.llm.availability import e_locale
    assert e_locale("http://192.168.1.50:8080/v1") is True
    assert e_locale("http://10.0.0.5:8000/v1") is True


def test_dominio_pubblico_non_e_locale():
    from app.llm.availability import e_locale
    assert e_locale("https://openrouter.ai/api/v1") is False


def test_ip_pubblico_non_e_locale():
    from app.llm.availability import e_locale
    assert e_locale("http://8.8.8.8:1234/v1") is False


def test_indirizzo_illeggibile_non_e_locale():
    """In dubbio, si presume che i dati escano: il default deve essere quello
    prudente, non quello comodo."""
    from app.llm.availability import e_locale
    assert e_locale("") is False
    assert e_locale("non-un-url") is False
