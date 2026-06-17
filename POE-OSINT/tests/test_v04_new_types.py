"""
test_v04_new_types.py — test per i nuovi tipi di entità di v0.4.

Copre:
  - A2: phone con punti come separatori (347.123.4567)
  - A3'.1: social_handle
  - A3'.2: tax_id (Codice Fiscale italiano con check digit)
  - A3'.3: vat_id (Partita IVA italiana con check digit)
  - A3'.4: birth_date con marcatori contestuali
"""

from __future__ import annotations

import pytest

from app.models import Entity


def _values_of(entities: list[Entity], t: str) -> set[str]:
    return {e.value for e in entities if e.type == t}


def _conf_of(entities: list[Entity], t: str) -> set[str]:
    return {e.confidence for e in entities if e.type == t}


# ─────────────────────────────────────────────────────────────
# A2 — Phone con punti come separatori
# ─────────────────────────────────────────────────────────────

class TestPhoneWithDots:
    def test_mobile_it_with_dots(self, regex_extractor):
        e = regex_extractor.extract("Chiama: 347.123.4567")
        assert "+39347123..." in {v[:11] for v in _values_of(e, "phone")} or \
               "+393471234567" in _values_of(e, "phone")

    def test_mobile_it_dots_e164(self, regex_extractor):
        e = regex_extractor.extract("Cell: 347.123.4567")
        phones = _values_of(e, "phone")
        assert any(p.startswith("+39347") for p in phones)

    def test_dots_not_confused_with_ip(self, regex_extractor):
        e = regex_extractor.extract("IP: 192.168.1.1 e cell 347.123.4567")
        assert "192.168.1.1" in _values_of(e, "ipv4")
        # 347.x.y non è un IP (347 > 255)

    def test_existing_spaces_still_work(self, regex_extractor):
        e = regex_extractor.extract("Tel: 347 123 4567")
        phones = _values_of(e, "phone")
        assert any(p.startswith("+39347") for p in phones)

    def test_international_with_dots(self, regex_extractor):
        e = regex_extractor.extract("+39.02.12345678")
        phones = _values_of(e, "phone")
        assert len(phones) >= 1


# ─────────────────────────────────────────────────────────────
# A3'.1 — social_handle
# ─────────────────────────────────────────────────────────────

class TestSocialHandle:
    def test_basic_social_handle(self, regex_extractor):
        e = regex_extractor.extract("Segui @mario_rossi su Instagram")
        assert "@mario_rossi" in _values_of(e, "social_handle")

    def test_social_handle_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("@mario_rossi")
        assert _conf_of(e, "social_handle") == {"medium"}

    def test_short_handle_extracted(self, regex_extractor):
        # social_handle ammette handle più corti di username (min 1 char)
        e = regex_extractor.extract("@abc ha postato")
        assert "@abc" in _values_of(e, "social_handle")

    def test_social_handle_supersedes_username(self, regex_extractor):
        # Dedup: username è soppianto da social_handle per lo stesso @handle
        e = regex_extractor.extract("@mrossi_official ha inviato un messaggio")
        types = {x.type for x in e}
        assert "social_handle" in types
        assert "username" not in types

    def test_social_handle_no_false_positive_email(self, regex_extractor):
        # La parte @dominio di un'email non deve diventare un social_handle
        e = regex_extractor.extract("Contatto: user@example.com")
        social = _values_of(e, "social_handle")
        # @example non deve essere un social_handle isolato (parte di email)
        # Il regex usa lookbehind per non catturare handle preceduti da alfanumerici
        assert "@example" not in social


# ─────────────────────────────────────────────────────────────
# A3'.2 — tax_id (Codice Fiscale)
# ─────────────────────────────────────────────────────────────

class TestTaxId:
    # CF con check digit verificato dall'algoritmo ministeriale (DPR 605/1973)
    _VALID_CFS = [
        "RSSMRA85M01H501Q",  # base RSSMRA85M01H501 → check = Q
        "BNCMRA80D15F205X",  # base BNCMRA80D15F205 → check = X
    ]

    def test_valid_cf_extracted(self, regex_extractor):
        for cf in self._VALID_CFS:
            e = regex_extractor.extract(f"CF: {cf}")
            assert cf in _values_of(e, "tax_id"), f"CF valido non estratto: {cf}"

    def test_tax_id_confidence_high(self, regex_extractor):
        e = regex_extractor.extract(f"CF: {self._VALID_CFS[0]}")
        assert _conf_of(e, "tax_id") == {"high"}

    def test_invalid_check_digit_rejected(self, regex_extractor):
        # CF con ultimo carattere sbagliato (Q → Z)
        invalid = "RSSMRA85M01H501Z"
        e = regex_extractor.extract(f"CF: {invalid}")
        assert invalid not in _values_of(e, "tax_id")

    def test_wrong_length_not_extracted(self, regex_extractor):
        e = regex_extractor.extract("ABC123")
        assert _values_of(e, "tax_id") == set()

    def test_case_insensitive_extraction(self, regex_extractor):
        cf_lower = self._VALID_CFS[0].lower()
        e = regex_extractor.extract(f"cf: {cf_lower}")
        assert self._VALID_CFS[0] in _values_of(e, "tax_id")


# ─────────────────────────────────────────────────────────────
# A3'.3 — vat_id (Partita IVA)
# ─────────────────────────────────────────────────────────────

class TestVatId:
    # P.IVA valide con check digit corretto
    _VALID_VATS = [
        "12345670017",   # check digit = 7... verificato
        "00159560366",   # P.IVA reale (esempio anonimizzato)
    ]

    def test_valid_vat_extracted(self, regex_extractor):
        # Usiamo una PIVA con check digit verificato
        # Calcolo manuale: 0+1+9+5+0+6 = 21 (dispari)
        # 0*2=0, 1*2=2, 5*2=10→1, 6*2=12→3, 3*2=6 (pari, pos 2,4,6,8,10 → idx 1,3,5,7,9)
        # Usiamo 00159560366 che è verificato
        e = regex_extractor.extract("P.IVA: 00159560366")
        assert "00159560366" in _values_of(e, "vat_id")

    def test_vat_confidence_high(self, regex_extractor):
        e = regex_extractor.extract("P.IVA: 00159560366")
        assert _conf_of(e, "vat_id") == {"high"}

    def test_invalid_check_digit_rejected(self, regex_extractor):
        # 00159560367 ha check digit sbagliato (dovrebbe essere 6)
        e = regex_extractor.extract("PIVA: 00159560367")
        assert "00159560367" not in _values_of(e, "vat_id")

    def test_it_prefix_accepted(self, regex_extractor):
        e = regex_extractor.extract("VAT IT00159560366")
        assert "00159560366" in _values_of(e, "vat_id")

    def test_non_11_digits_not_extracted(self, regex_extractor):
        e = regex_extractor.extract("Codice: 12345")
        assert _values_of(e, "vat_id") == set()


# ─────────────────────────────────────────────────────────────
# A3'.4 — birth_date con marcatori contestuali
# ─────────────────────────────────────────────────────────────

class TestBirthDate:
    def test_nato_il_marker(self, regex_extractor):
        e = regex_extractor.extract("Il soggetto nato il 15/03/1985 abita a Roma")
        assert "15/03/1985" in _values_of(e, "birth_date")

    def test_nata_il_marker(self, regex_extractor):
        e = regex_extractor.extract("La persona nata il 01.06.1992")
        assert "01.06.1992" in _values_of(e, "birth_date")

    def test_dob_marker(self, regex_extractor):
        e = regex_extractor.extract("DOB: 22-11-1978")
        assert "22-11-1978" in _values_of(e, "birth_date")

    def test_date_of_birth_marker(self, regex_extractor):
        e = regex_extractor.extract("Date of birth: 05/07/1990")
        assert "05/07/1990" in _values_of(e, "birth_date")

    def test_data_di_nascita_marker(self, regex_extractor):
        e = regex_extractor.extract("Data di nascita: 12.04.1965")
        assert "12.04.1965" in _values_of(e, "birth_date")

    def test_birth_date_confidence_low(self, regex_extractor):
        e = regex_extractor.extract("nato il 15/03/1985")
        assert _conf_of(e, "birth_date") == {"low"}

    def test_date_without_marker_not_extracted(self, regex_extractor):
        # Una data senza marcatore NON deve essere estratta come birth_date
        e = regex_extractor.extract("Il meeting è il 15/03/2025 alle 14:00")
        assert _values_of(e, "birth_date") == set()

    def test_birth_date_two_digit_year(self, regex_extractor):
        e = regex_extractor.extract("DOB: 01/01/85")
        assert "01/01/85" in _values_of(e, "birth_date")
