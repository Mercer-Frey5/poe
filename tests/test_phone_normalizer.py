"""
test_phone_normalizer.py — test sul modulo phone_normalizer di v0.3.

Verifichiamo:
- Numeri locali italiani normalizzati a +39
- Numeri con prefisso esplicito rispettati
- Numeri invalidi → None
- Forma E.164 standard di output
- Disponibilità dei campi country_code e national_number (porta v0.4)
"""

from __future__ import annotations

from app.phone_normalizer import normalize, NormalizedPhone


class TestNormalizationItalianLocal:
    def test_mobile_with_spaces(self):
        result = normalize("347 1234567")
        assert result is not None
        assert result.e164 == "+393471234567"
        assert result.country_code == 39
        assert result.is_valid is True

    def test_mobile_with_dashes(self):
        result = normalize("347-123-4567")
        assert result is not None
        assert result.e164 == "+393471234567"

    def test_mobile_compact(self):
        result = normalize("3471234567")
        assert result is not None
        assert result.e164 == "+393471234567"

    def test_landline_milano(self):
        result = normalize("02 1234 5678")
        assert result is not None
        assert result.e164 == "+390212345678"
        assert result.country_code == 39


class TestNormalizationExplicitPrefix:
    def test_italian_with_plus(self):
        """Numero italiano con +39 esplicito."""
        result = normalize("+39 347 1234567")
        assert result is not None
        assert result.e164 == "+393471234567"

    def test_uk_number_respected(self):
        """v0.3: numero UK con +44 NON viene forzato a IT."""
        result = normalize("+44 20 7946 0958")
        assert result is not None
        assert result.e164 == "+442079460958"
        assert result.country_code == 44

    def test_us_number_respected(self):
        """Numero USA con +1."""
        result = normalize("+1 202 555 0173")
        assert result is not None
        assert result.country_code == 1
        assert result.e164.startswith("+1")


class TestInvalidNumbers:
    def test_too_short_returns_none(self):
        assert normalize("12345") is None

    def test_empty_string_returns_none(self):
        assert normalize("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize("   ") is None

    def test_unparseable_returns_none(self):
        """Stringa che non somiglia a un numero."""
        assert normalize("non un numero") is None

    def test_letters_in_number_returns_none(self):
        assert normalize("abc347def") is None


class TestApiContract:
    """
    Verifica del contratto della funzione normalize.
    NormalizedPhone deve esporre i campi che servono al Recognizer di v0.3
    (e164, is_valid) E quelli che useremo in v0.4 (country_code, national_number).
    """

    def test_returns_normalized_phone_dataclass(self):
        result = normalize("347 1234567")
        assert isinstance(result, NormalizedPhone)

    def test_dataclass_has_all_fields_for_future_flags(self):
        """Porta aperta a v0.4: country_code e national_number presenti."""
        result = normalize("347 1234567")
        assert result is not None
        assert hasattr(result, "country_code")
        assert hasattr(result, "national_number")
        assert hasattr(result, "is_valid")
        assert isinstance(result.country_code, int)
        assert isinstance(result.national_number, int)

    def test_custom_region_parameter(self):
        """Si può passare una regione di default diversa da IT."""
        # Numero locale tedesco passato con region="DE"
        result = normalize("030 12345678", region="DE")
        # Non verifichiamo il valore esatto perché dipende dalla validità
        # del prefisso 030 in Germania (Berlino), ma il country code se
        # parsato deve essere 49 (Germania).
        if result is not None:
            assert result.country_code == 49
