"""
regex_extractor.py — estrazione di entità a pattern forte via regex (v0.4).

Tipi coperti:
    v0.1: email, ipv4, url, domain, hash_md5, username, phone
    v0.2: + hash_sha256, cve
    v0.4: + tax_id, vat_id, social_handle, birth_date
          + phone con punti come separatori (A2)
          + confidence su ogni entità
          + metadata su phone (country_code, national_number)

Livelli di confidenza assegnati per tipo:
    high:   phone (validato da phonenumbers.is_valid_number),
            tax_id (check digit matematico CF),
            vat_id (check digit P.IVA)
    medium: email, ipv4, url, domain, hash_md5, hash_sha256, cve,
            social_handle
    low:    username, birth_date
"""

from __future__ import annotations

import ipaddress
import re

from app.config_loader import load_yaml_list
from app.extractors.base import BaseExtractor
from app.models import Entity
from app.phone_normalizer import normalize as _normalize_phone


# ─────────────────────────────────────────────────────────────
# Pattern esistenti (v0.1/v0.2, invariati salvo phone)
# ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

_URL_RE = re.compile(
    r"https?://[^\s<>\"'\)\]]+",
    re.IGNORECASE,
)

_DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,24}\b"
)

# Le voci di tld_list.yaml sono già nel formato corretto (es. "com").
_KNOWN_TLDS: frozenset[str] = frozenset(t.lower() for t in load_yaml_list("tld_list.yaml"))

# Le voci di suspicious_tlds.yaml sono nel formato "- .xyz" → strip leading dot.
_SUSPICIOUS_TLDS: frozenset[str] = frozenset(
    t.lstrip(".").lower() for t in load_yaml_list("suspicious_tlds.yaml")
)


def _has_known_tld(domain: str) -> bool:
    tld = domain.rsplit(".", 1)[-1].lower()
    return tld in _KNOWN_TLDS


def _is_suspicious_tld(domain: str) -> bool:
    tld = domain.rsplit(".", 1)[-1].lower()
    return tld in _SUSPICIOUS_TLDS


_HASH_MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
_HASH_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]{3,30}\b")

# Phone: esteso in v0.4 per supportare punti come separatori (A2).
# Rami aggiunti:
#   - mobile IT con due punti: 347.123.4567
#   - internazionale con punti: +39.02.1234.5678
# Test effettuati contro IP (primo ottetto >255 per mobile → nessun conflitto),
# hash (solo hex, mai decimali puri) e URL (prefisso http/).
_PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"\+\d{1,3}[\s.\-]?\d{2,4}[\s.\-]?\d{3,4}[\s.\-]?\d{3,5}"  # +xx internazionale
    r"|"
    r"3\d{2}\.\d{3}\.\d{4}"              # mobile IT con punti: 347.123.4567
    r"|"
    r"3\d{2}[\s\-]\d{3}[\s\-]?\d{4}"    # mobile IT con spazi/trattini: 347 123 4567
    r"|"
    r"3\d{8,9}"                          # mobile IT senza separatori: 3471234567
    r"|"
    r"0\d{1,4}[\s.\-]?\d{4,8}"          # fisso IT
    r")(?!\d)"
)

_URL_TRAILING_CHARS = ".,;:!?"


def _clean_url(raw: str) -> str:
    while raw and raw[-1] in _URL_TRAILING_CHARS:
        raw = raw[:-1]
    return raw


# ─────────────────────────────────────────────────────────────
# Pattern v0.4 — nuovi tipi
# ─────────────────────────────────────────────────────────────

# social_handle (A3'.1 fase 1): pattern @handle identico a username ma
# tipo distinto. In v0.5 fase 2 riceverà classificazione di piattaforma.
# Confidenza media (pattern formale, nessuna verifica piattaforma).
_SOCIAL_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]{1,50}\b")

# tax_id — Codice Fiscale italiano (A3'.2)
# Formato: 6 lettere (cognome) + 2 cifre (anno) + 1 lettera (mese) +
#          2 cifre (giorno+sesso) + 4 char (comune) + 1 lettera (controllo)
# Check digit verificato con algoritmo ministeriale.
_TAX_ID_RE = re.compile(
    r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b"
)

# vat_id — Partita IVA italiana (A3'.3)
# Formato: opzionale "IT" + 11 cifre. Check digit Luhn-like.
_VAT_ID_RE = re.compile(r"\b(?:IT\s*)?(\d{11})\b", re.IGNORECASE)

# birth_date (A3'.4 fase 1): solo date precedute da marcatori contestuali espliciti.
# Fase 2 (v0.5): pattern più ampi senza marcatori.
# Confidenza bassa: il marcatore riduce l'ambiguità ma non la elimina.
_BIRTH_DATE_RE = re.compile(
    r"(?:nato\s+il|nata\s+il|data\s+di\s+nascita|nascit[ao]\s*:|DOB\s*:|"
    r"date\s+of\s+birth\s*:?)\s*"
    r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# Pattern v0.5 — address (Task 8)
# ─────────────────────────────────────────────────────────────

_ADDRESS_RE = re.compile(
    r"\b(?:Via|Viale|Corso|Piazza|Largo|Vicolo|Strada|Lungarno|Borgo|Contrada|Frazione)\s+"
    r"(?:[A-Za-zÀ-ÿ'''\-]+\s*){1,5}"
    r",?\s*\d{1,5}"
    r"(?:(?:,?\s*\d{5})\s+[A-Za-zÀ-ÿ\s]{2,30})?",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────
# Bogon IP helpers (Task 7)
# ─────────────────────────────────────────────────────────────

_BOGON_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
]


def _bogon_type(ip_str: str) -> str | None:
    """Return bogon category string or None if publicly routable."""
    try:
        addr = ipaddress.ip_address(ip_str)
        if addr.is_loopback:
            return "loopback"
        if addr.is_private:
            return "private"
        for net in _BOGON_NETWORKS:
            if addr in net:
                return "reserved"
    except ValueError:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# Check digit: tax_id (Codice Fiscale)
# ─────────────────────────────────────────────────────────────

# Tabella valori per posizioni dispari (1-indexed) del CF.
# Fonte: DPR 605/1973, Allegato A.
_CF_ODD: dict[str, int] = {
    '0': 1,  '1': 0,  '2': 5,  '3': 7,  '4': 9,  '5': 13,
    '6': 15, '7': 17, '8': 19, '9': 21,
    'A': 1,  'B': 0,  'C': 5,  'D': 7,  'E': 9,  'F': 13,
    'G': 15, 'H': 17, 'I': 19, 'J': 21, 'K': 2,  'L': 4,
    'M': 18, 'N': 20, 'O': 11, 'P': 3,  'Q': 6,  'R': 8,
    'S': 12, 'T': 14, 'U': 16, 'V': 10, 'W': 22, 'X': 25,
    'Y': 24, 'Z': 23,
}


def _validate_tax_id(cf: str) -> bool:
    """Verifica il check digit del Codice Fiscale italiano."""
    cf = cf.upper()
    if len(cf) != 16:
        return False
    total = 0
    for i, c in enumerate(cf[:15]):
        if i % 2 == 0:  # posizione dispari (1-indexed)
            total += _CF_ODD.get(c, 0)
        else:           # posizione pari (1-indexed)
            total += int(c) if c.isdigit() else (ord(c) - ord('A'))
    expected = chr(ord('A') + (total % 26))
    return expected == cf[15]


# ─────────────────────────────────────────────────────────────
# Check digit: vat_id (Partita IVA)
# ─────────────────────────────────────────────────────────────

def _is_valid_date(date_str: str) -> bool:
    """Verifica che giorno (1-31) e mese (1-12) siano semanticamente plausibili.

    Non controlla giorni-per-mese (es. 31/02 passa). Per birth_date fase 1
    è sufficiente: il marcatore contestuale ha già filtrato i FP grossolani.
    """
    parts = re.split(r"[/.\-]", date_str)
    if len(parts) != 3:
        return False
    try:
        day, month = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 1 <= day <= 31 and 1 <= month <= 12


def _validate_vat_id(digits: str) -> bool:
    """Verifica il check digit della Partita IVA italiana (11 cifre)."""
    if len(digits) != 11 or not digits.isdigit():
        return False
    total = 0
    for i, d in enumerate(digits[:10]):
        n = int(d)
        if i % 2 == 0:  # posizioni dispari (1-indexed: 1,3,5,7,9)
            total += n
        else:           # posizioni pari (1-indexed: 2,4,6,8,10)
            doubled = n * 2
            total += doubled if doubled < 10 else doubled - 9
    expected = (10 - (total % 10)) % 10
    return expected == int(digits[10])


# ─────────────────────────────────────────────────────────────
# Classe
# ─────────────────────────────────────────────────────────────

class RegexExtractor(BaseExtractor):
    """Estrattore deterministico basato su regex. v0.4."""

    def extract(self, text: str) -> list[Entity]:
        found: set[Entity] = set()

        for m in _EMAIL_RE.finditer(text):
            found.add(Entity("email", m.group(), confidence="medium"))

        for m in _IPV4_RE.finditer(text):
            ip_val = m.group()
            btype = _bogon_type(ip_val)
            meta: dict = {"extractor": "regex"}
            if btype:
                meta["bogon"] = True
                meta["bogon_type"] = btype
            found.add(Entity(
                type="ipv4",
                value=ip_val,
                confidence="low" if btype else "medium",
                metadata=meta,
            ))

        for m in _URL_RE.finditer(text):
            found.add(Entity("url", _clean_url(m.group()), confidence="medium"))

        for m in _DOMAIN_RE.finditer(text):
            value = m.group().lower()
            if _has_known_tld(value):
                meta = {"suspicious_tld": True} if _is_suspicious_tld(value) else {}
                found.add(Entity("domain", value, confidence="medium", metadata=meta))

        for m in _HASH_SHA256_RE.finditer(text):
            found.add(Entity("hash_sha256", m.group().lower(), confidence="medium"))

        for m in _HASH_MD5_RE.finditer(text):
            found.add(Entity("hash_md5", m.group().lower(), confidence="medium"))

        for m in _CVE_RE.finditer(text):
            value = "CVE-" + m.group().split("-", 1)[1]
            found.add(Entity("cve", value, confidence="medium"))

        for m in _USERNAME_RE.finditer(text):
            found.add(Entity("username", m.group(), confidence="low"))

        for m in _PHONE_RE.finditer(text):
            raw = m.group()
            normalized = _normalize_phone(raw)
            if normalized is None:
                continue
            found.add(Entity(
                "phone",
                value=normalized.e164,
                original=raw,
                confidence="high",
                metadata={
                    "country_code": normalized.country_code,
                    "national_number": normalized.national_number,
                    "region": normalized.region,
                },
            ))

        # social_handle (A3'.1 fase 1)
        for m in _SOCIAL_HANDLE_RE.finditer(text):
            found.add(Entity("social_handle", m.group(), confidence="medium"))

        # tax_id — Codice Fiscale (A3'.2)
        for m in _TAX_ID_RE.finditer(text):
            cf = m.group().upper()
            if _validate_tax_id(cf):
                found.add(Entity("tax_id", cf, confidence="high"))

        # vat_id — Partita IVA (A3'.3)
        for m in _VAT_ID_RE.finditer(text):
            digits = m.group(1)  # solo le 11 cifre, senza prefisso IT
            if _validate_vat_id(digits):
                found.add(Entity("vat_id", digits, confidence="high"))

        # birth_date — solo con marcatori contestuali (A3'.4 fase 1)
        # Validazione semantica: giorno 1-31, mese 1-12. Anno non vincolato
        # qui (date future tipo nato il 01/01/2099 sono comunque scartate
        # come improbabili a livello applicativo, ma il regex non lo blocca).
        for m in _BIRTH_DATE_RE.finditer(text):
            date_str = m.group(1)
            if _is_valid_date(date_str):
                found.add(Entity("birth_date", date_str, confidence="low"))

        # address (Task 8)
        for m in _ADDRESS_RE.finditer(text):
            full = m.group().strip()
            city = ""
            city_m = re.search(r"\d{5}\s+([A-Za-zÀ-ÿ\s]+)$", full)
            if city_m:
                city = city_m.group(1).strip()
            found.add(Entity(
                type="address",
                value=full.lower(),
                confidence="medium",
                metadata={"extractor": "regex", "full_address": full, "city": city},
            ))

        # Deduplicate: username is superseded by social_handle for same value
        entities = list(found)
        social_values = {e.value for e in entities if e.type == "social_handle"}
        entities = [e for e in entities if not (e.type == "username" and e.value in social_values)]

        return entities
