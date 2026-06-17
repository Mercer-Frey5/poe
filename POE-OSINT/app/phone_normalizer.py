"""
phone_normalizer.py — normalizzazione di numeri telefonici in formato E.164.

In v0.2 il RegexExtractor catturava numeri telefonici come stringhe grezze
(rimozione whitespace, niente altro). In v0.3 abbiamo:
- Parsing strutturato via libreria `phonenumbers` (port di libphonenumber)
- Default regionale italiano: numeri locali senza prefisso → assumiamo +39
- Rispetto del prefisso esplicito: se il numero ha già +XX, parser usa
  quel country code (anche per numeri esteri trovati in testi italiani)
- Validazione: numeri sintatticamente parsabili ma semanticamente invalidi
  (es. troppo corti) vengono scartati

Pattern original/value:
- `original` = forma testuale come appariva nel testo (es. "347 1234567")
- `value`    = forma E.164 normalizzata (es. "+393471234567")

Porta aperta a v0.4:
La funzione interna `normalize()` ritorna un dict ricco con country_code
e national_number, anche se il Recognizer in v0.3 usa solo `e164` e
`is_valid`. Quando in v0.4 verrà introdotto il design dei flag su Entity,
estrarre il country code in superficie sarà cambio del Recognizer, non
del normalizer. Costo zero oggi, sblocco totale domani.
"""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


# Regione di default per numeri privi di prefisso internazionale.
# Convenzione del progetto: POE è uno strumento per uso italiano,
# i numeri locali si assumono italiani. Numeri con +XX esplicito
# vengono comunque rispettati dalla libreria.
DEFAULT_REGION = "IT"


@dataclass(frozen=True)
class NormalizedPhone:
    e164: str           # forma normalizzata E.164, es "+393471234567"
    country_code: int   # codice paese ITU-T, es. 39
    national_number: int
    is_valid: bool
    region: str         # codice ISO-3166-1 alpha-2, es "IT"


def normalize(raw: str, region: str = DEFAULT_REGION) -> NormalizedPhone | None:
    """
    Normalizza una stringa che (presumibilmente) contiene un numero
    di telefono. Ritorna None se il parsing fallisce o se il numero
    risulta invalido (troppo corto, prefisso inesistente, ecc.).

    Strategia:
    1. parse(raw, region): la libreria gestisce automaticamente i casi
       "+XX esplicito" vs "numero locale". Se c'è +XX nel testo, lo usa;
       altrimenti applica il default `region`.
    2. is_valid_number(): scarta numeri sintatticamente parsabili ma
       semanticamente impossibili (es. "12345" diventerebbe +3912345
       sintatticamente ma non è un numero italiano valido).

    Args:
        raw: stringa con il numero, può contenere whitespace, parentesi,
             punti separatori, prefisso esplicito o no
        region: codice ISO-3166-1 alpha-2 della regione di default
                (es. "IT", "US", "DE")

    Returns:
        NormalizedPhone se il numero è parsabile e valido, None altrimenti
    """
    if not raw or not raw.strip():
        return None

    try:
        parsed = phonenumbers.parse(raw, region)
    except NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    region_code = phonenumbers.region_code_for_number(parsed) or ""
    return NormalizedPhone(
        e164=phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
        country_code=parsed.country_code,
        national_number=parsed.national_number,
        is_valid=True,
        region=region_code,
    )
