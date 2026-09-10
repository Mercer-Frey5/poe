"""demo_seed.py — osservazioni demo per test manuale rapido dopo un restart.

ATTENZIONE — SOLO SVILUPPO: attivo esclusivamente con POE_DEMO_DATA=1
nell'ambiente (.env). DA RIMUOVERE prima di qualunque uso reale/pubblico.

IP scelti con cura: devono superare `ipaddress.ip_address(...).is_global`
(altrimenti POE li tratta come bogon/privati — vedi bug reale osservato:
i range RFC 5737 "documentation" risultano is_private=True per lo stdlib
Python, anche se non sono RFC 1918). Usati solo IP pubblici reali e
notoriamente innocui/di test (resolver DNS pubblici, scanme.nmap.org —
il target di test ufficiale del progetto Nmap). Hash/domini sono inventati.

Seed una sola volta: skip se il DB ha già osservazioni, per non duplicare
a ogni riavvio (--reload di uvicorn riavvia a ogni salvataggio file)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app import storage
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["seed_demo_data"]

_YOUNG_DOMAIN_DATE = (date.today() - timedelta(days=5)).isoformat()
_OLD_DOMAIN_DATE = (date.today() - timedelta(days=365 * 8)).isoformat()
_FRESH_FEED_DATE = date.today().isoformat() + "T00:00:00"
_RECENT_FEED_DATE = (date.today() - timedelta(days=20)).isoformat() + "T00:00:00"
_OLD_FEED_DATE = (date.today() - timedelta(days=90)).isoformat() + "T00:00:00"


def _demo_observations() -> list[tuple[str, list[Entity], str]]:
    return [
        (
            "Traffico sospetto verso 45.33.32.156 (scanme.nmap.org — target di "
            "test pubblico del progetto Nmap, usato qui solo come IP reale/"
            "pubblico di comodo). Dominio phishing login-secure-bank.xyz, "
            "riferimento CVE-2024-3400.",
            [
                Entity("ipv4", "45.33.32.156", confidence="high", metadata={
                    "country": "United States", "city": "Seattle", "isp": "Linode, LLC",
                    "rdap_name": "SCANME-NET", "rdap_country": "US", "rdap_cidr": "45.33.32.0/24",
                    "rdap_org": "Linode, LLC", "rdap_abuse": "abuse@linode.com",
                    "ripe_abuse_contacts": "abuse@linode.com",
                    "reputation": {
                        "malicious": True, "sources": ["threatfox", "urlhaus"],
                        "threat": "Cobalt Strike C2", "reference": "https://threatfox.abuse.ch/",
                        "updated_at": _FRESH_FEED_DATE,
                        "hits": [
                            {"source": "threatfox", "threat": "Cobalt Strike C2",
                             "reference": "https://threatfox.abuse.ch/ioc/999999/",
                             "updated_at": _FRESH_FEED_DATE},
                            {"source": "urlhaus", "threat": "Cobalt Strike C2",
                             "reference": "https://urlhaus.abuse.ch/url/999999/",
                             "updated_at": _RECENT_FEED_DATE},
                        ],
                    },
                }),
                Entity("domain", "login-secure-bank.xyz", confidence="medium", metadata={
                    "suspicious_tld": True, "creation_date": _YOUNG_DOMAIN_DATE,
                    "registrar": "NameCheap Inc.", "registrant_country": "unknown",
                    "derived_from": "url:https://login-secure-bank.xyz/verify",
                }),
                Entity("cve", "CVE-2024-3400", confidence="high"),
            ],
            "[DEMO] IP malevolo (C2) + dominio phishing + CVE — badge di rischio",
        ),
        (
            "Rete interna: gateway 192.168.1.1, loopback 127.0.0.1, "
            "CGNAT 100.64.0.5 — nessuna minaccia nota, IP non instradabili.",
            [
                Entity("ipv4", "192.168.1.1", confidence="high",
                       metadata={"bogon": True, "bogon_type": "private"}),
                Entity("ipv4", "127.0.0.1", confidence="high",
                       metadata={"bogon": True, "bogon_type": "loopback"}),
                Entity("ipv4", "100.64.0.5", confidence="medium",
                       metadata={"bogon": True, "bogon_type": "reserved"}),
            ],
            "[DEMO] Cluster IP privati/bogon — nessuna minaccia, IP non instradabili",
        ),
        (
            "Contatto pulito: Mario Rossi, mario.rossi@example.com, "
            "+39 351 234 5678, IP pubblico 8.8.8.8 (Google DNS, nessun match "
            "reputation).",
            [
                Entity("person_name", "Mario Rossi", confidence="medium"),
                Entity("email", "mario.rossi@example.com", confidence="high"),
                Entity("phone", "+393512345678", confidence="medium",
                       metadata={"region": "IT"}),
                Entity("ipv4", "8.8.8.8", confidence="high", metadata={
                    "country": "United States", "city": "Mountain View", "isp": "Google LLC",
                    "rdap_name": "GOOGLE", "rdap_country": "US", "rdap_cidr": "8.8.8.0/24",
                }),
            ],
            "[DEMO] Contatto pulito + IP pubblico pulito (nessun match reputation)",
        ),
        (
            "Campione malware: hash SHA256 noto in MalwareBazaar, URL di "
            "distribuzione in URLhaus, hash MD5 collaterale senza match noto.",
            [
                Entity("hash_sha256",
                       "aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111",
                       confidence="high", metadata={
                           "reputation": {
                               "malicious": True, "sources": ["malwarebazaar"],
                               "threat": "AgentTesla", "reference": "https://bazaar.abuse.ch/sample/aaaa.../",
                               "updated_at": _OLD_FEED_DATE,
                               "hits": [{"source": "malwarebazaar", "threat": "AgentTesla",
                                        "reference": "https://bazaar.abuse.ch/sample/aaaa.../",
                                        "updated_at": _OLD_FEED_DATE}],
                           },
                       }),
                Entity("url", "http://malware-drop-example.top/payload.exe",
                       confidence="medium", metadata={
                           "suspicious_tld": True,
                           "reputation": {
                               "malicious": True, "sources": ["urlhaus"],
                               "threat": "AgentTesla", "reference": "https://urlhaus.abuse.ch/url/888888/",
                               "updated_at": _RECENT_FEED_DATE,
                               "hits": [{"source": "urlhaus", "threat": "AgentTesla",
                                        "reference": "https://urlhaus.abuse.ch/url/888888/",
                                        "updated_at": _RECENT_FEED_DATE}],
                           },
                       }),
                Entity("hash_md5", "0123456789abcdef0123456789abcdef",
                       confidence="high"),
            ],
            "[DEMO] Hash e URL malevoli (malware) + hash senza match noto",
        ),
        (
            "Dominio pubblico senza segnali di rischio, utile per testare i "
            "lookup live (crt.sh/urlscan.io) su un caso pulito: "
            "example-research.org, registrato da tempo.",
            [
                Entity("domain", "example-research.org", confidence="high", metadata={
                    "registrar": "Gandi SAS", "creation_date": _OLD_DOMAIN_DATE,
                    "expiration_date": (date.today() + timedelta(days=200)).isoformat(),
                    "registrant_country": "FR", "status": "active", "dnssec": "unsigned",
                }),
            ],
            "[DEMO] Dominio pulito — test lookup live (crt.sh/urlscan.io)",
        ),
        (
            "Profilo persona (scope OSINT persone): Giulia Bianchi, "
            "giulia.bianchi@example.org, username @giuliab, +39 351 234 5678, "
            "codice fiscale BNCGLI85M41H501Y (esempio didattico, non reale).",
            [
                Entity("person_name", "Giulia Bianchi", confidence="medium"),
                Entity("email", "giulia.bianchi@example.org", confidence="high"),
                Entity("username", "giuliab", confidence="medium"),
                Entity("phone", "+393512345678", confidence="medium", metadata={"region": "IT"}),
                Entity("tax_id", "BNCGLI85M41H501Y", confidence="high"),
            ],
            "[DEMO] Profilo persona OSINT — email/username/telefono (dati fittizi)",
        ),
    ]


def seed_demo_data() -> None:
    """Seed idempotente: no-op se il DB ha già almeno un'osservazione."""
    if storage.get_recent(limit=1):
        return

    observations = _demo_observations()
    for raw_input, entities, label in observations:
        oid = storage.save_observation(raw_input, entities)
        storage.set_label(oid, label)

    logger.warning(
        "POE_DEMO_DATA attivo: %d osservazioni demo seedate (IOC finti/di "
        "test, nessun dato reale sensibile). Disattiva POE_DEMO_DATA prima "
        "di un uso reale.",
        len(observations),
    )
