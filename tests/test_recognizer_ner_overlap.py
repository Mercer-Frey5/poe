"""Regressione: spaCy NER a volte tagga un dominio (es. jx.tigronesizzles.com)
ANCHE come person_name. Due entità con lo STESSO valore ma tipi diversi rompono
il rendering a valle (catalog_resources è un dict keyed per valore: la seconda
sovrascrive la prima), per cui la 'sezione dominio' non parte / mostra i lookup
da person_name. Il Recognizer deve scartare il tipo NER 'soft' quando il valore
è già un tipo strutturato (domain/email/url/ip/hash/...).
"""
from __future__ import annotations

from app.models import Entity
from app.recognizer import Recognizer


def _values_of(entities, t):
    return {e.value for e in entities if e.type == t}


def test_person_name_suppressed_when_value_is_domain(regex_extractor, fake_spacy):
    # regex riconosce il dominio; spaCy lo scambia per person_name (falso positivo).
    spacy = fake_spacy([Entity("person_name", "jx.tigronesizzles.com")])
    rec = Recognizer(regex_extractor, spacy)
    ents = rec.recognize("jx.tigronesizzles.com")

    assert "jx.tigronesizzles.com" in _values_of(ents, "domain")  # il dominio resta
    assert "jx.tigronesizzles.com" not in _values_of(ents, "person_name")  # NER scartato
    # una sola entità con quel valore -> niente collisione in catalog_resources
    assert len([e for e in ents if e.value == "jx.tigronesizzles.com"]) == 1


def test_real_person_name_is_kept(regex_extractor, fake_spacy):
    # un vero nome (non è un IOC strutturato) deve restare.
    spacy = fake_spacy([Entity("person_name", "Mario Rossi")])
    rec = Recognizer(regex_extractor, spacy)
    ents = rec.recognize("Ha chiamato Mario Rossi ieri")
    assert "Mario Rossi" in _values_of(ents, "person_name")


# --- tuning alla fonte: lo SpacyExtractor scarta i candidati a forma di IOC ---
def test_is_ioc_shaped_rejects_ioc_forms():
    from app.extractors.spacy_extractor import _is_ioc_shaped
    assert _is_ioc_shaped("jx.tigronesizzles.com")   # dominio (punto senza spazi)
    assert _is_ioc_shaped("example.com")
    assert _is_ioc_shaped("admin@x.com")             # email
    assert _is_ioc_shaped("http://x.com/a")          # url
    assert _is_ioc_shaped("CVE-2021-1234")           # codice con cifre


def test_is_ioc_shaped_keeps_real_names():
    from app.extractors.spacy_extractor import _is_ioc_shaped
    assert not _is_ioc_shaped("Mario Rossi")
    assert not _is_ioc_shaped("Anna")
    assert not _is_ioc_shaped("J.R.R. Tolkien")      # iniziali puntate ma CON spazi
