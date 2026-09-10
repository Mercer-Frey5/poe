"""
test_spacy_stoplist.py — test sulla stoplist label-words del SpacyExtractor.

Testiamo il filtro `_is_label_word` direttamente, senza caricare i
modelli spaCy reali (pesanti). I test di accettazione integrano la
stoplist nella pipeline completa quando i modelli sono presenti.
"""

from __future__ import annotations

from app.extractors.spacy_extractor import _is_label_word


class TestStoplist:
    def test_known_label_italian(self):
        assert _is_label_word("Contatto") is True
        assert _is_label_word("Mittente") is True
        assert _is_label_word("Destinatario") is True

    def test_known_label_english(self):
        assert _is_label_word("From") is True
        assert _is_label_word("Subject") is True

    def test_case_insensitive(self):
        assert _is_label_word("CONTATTO") is True
        assert _is_label_word("contatto") is True
        assert _is_label_word("Contatto") is True

    def test_whitespace_tolerant(self):
        assert _is_label_word("  Contatto  ") is True

    def test_real_name_not_in_stoplist(self):
        assert _is_label_word("Mario Rossi") is False
        assert _is_label_word("John Smith") is False
        assert _is_label_word("Marco") is False

    def test_partial_match_not_filtered(self):
        """La stoplist matcha parole esatte, non substring."""
        # "Contattore" contiene "Contatt" ma non è una label.
        assert _is_label_word("Contattore") is False
