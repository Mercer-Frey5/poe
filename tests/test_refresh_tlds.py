"""TDD per la validazione TLD di scripts/refresh_tlds.py.

Il bug: la validazione usava `tld.isalnum()`, che scarta le TLD IDN nella lista
IANA (in forma punycode `xn--...`, con trattini) -> il refresh crashava e la
lista restava il seed di ~165 TLD, per cui domini con TLD non-seed (es. .cyou)
NON venivano riconosciuti come dominio (-> "sezione dominio non parte").
"""
from scripts.refresh_tlds import _is_valid_tld


def test_accepts_common_and_new_gtld():
    assert _is_valid_tld("com")
    assert _is_valid_tld("cyou")   # gTLD mancante nel seed = causa del bug utente
    assert _is_valid_tld("dev")
    assert _is_valid_tld("zip")


def test_accepts_punycode_idn():
    assert _is_valid_tld("xn--p1ai")          # .рф
    assert _is_valid_tld("xn--80akhbyknj4f")  # .испытание


def test_rejects_garbage():
    assert not _is_valid_tld("a")     # troppo corta
    assert not _is_valid_tld("ab!")   # carattere non ammesso
    assert not _is_valid_tld("")
    assert not _is_valid_tld("do.t")  # il punto non è ammesso in una TLD
