"""live_lookup.py — interrogazioni on-demand (click esplicito, mai automatiche)
a servizi gratuiti senza API key: crt.sh (Certificate Transparency) e urlscan.io
(storico scan pubblici) per domini/URL, NVD (NIST) per CVE, Team Cymru whois
per IP → ASN. Più AbuseIPDB/VirusTotal/Shodan, che richiedono una API key
(lette da ABUSEIPDB_API_KEY/VIRUSTOTAL_API_KEY/SHODAN_API_KEY, vedi
.env.example) — assente = {"ok": False}, il catalogo mostra il link esterno
invece del lookup (vedi app/main.py::_live_resource_ids). Difensivo: non
solleva mai, ritorna {"ok": False, "error": ...} su qualunque fallimento
(rete, parsing, timeout, key mancante)."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import phonenumbers
from phonenumbers import carrier, geocoder

_TIMEOUT = 6.0
_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_WMN_DATA_PATH = Path(__file__).resolve().parent / "config" / "wmn-data.json"
_IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
# Dominio "nudo" senza schema/path (un URL vero ha sempre "://" o "/"): serve
# a distinguere "example.com" (oggetto domains su VT) da un URL vero e proprio
# (oggetto urls, con resource id base64) usando solo la forma del valore.
_BARE_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def _friendly_http_error(exc: Exception, service: str) -> str:
    """Messaggio leggibile per gli errori HTTP, al posto del testo grezzo
    dell'eccezione httpx. SICUREZZA: non restituisce MAI str(exc) — l'URL della
    richiesta può contenere la API key in query string (es. Hunter/Shodan
    ?api_key=/?key=), e finirebbe in chiaro nel messaggio d'errore mostrato
    all'utente. Sempre un messaggio derivato solo dal codice/tipo, mai l'URL."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return (
                f"{service}: chiave rifiutata (non valida, oppure il piano "
                f"dell'account non include questa funzione)"
            )
        if code == 400:
            return f"{service}: richiesta rifiutata (valore non valido o non verificabile da questo servizio)"
        if code == 429:
            return f"{service}: quota esaurita, riprova più tardi"
        if code >= 500:
            return f"{service}: servizio temporaneamente non disponibile ({code})"
        return f"{service}: risposta inattesa ({code})"
    # RequestError (timeout/connessione/…) o altro: messaggio generico, MAI
    # l'eccezione grezza (può includere l'URL con la key).
    return f"{service}: errore di rete o risposta non valida"


# Codici che indicano un guasto TRANSITORIO del gateway (servizio sovraccarico),
# quindi vale la pena ritentare: crt.sh in primis risponde 502 in modo
# intermittente. NON includono i 4xx (deterministici) né 500 (spesso un errore
# applicativo reale, non transitorio come i gateway 502/503/504).
_RETRY_STATUSES = frozenset({502, 503, 504})


async def _get_with_retry(url: str, *, retries: int = 2, backoff: float = 0.5,
                          **kwargs) -> httpx.Response:
    """GET con retry automatico sugli errori TRANSITORI: 502/503/504 e
    timeout/connessione. Servizi gratuiti come crt.sh rispondono spesso 502
    intermittente e un retry ravvicinato riesce — così l'utente non deve
    cliccare 'Riprova' a mano. NON ritenta i 4xx (401/403/404/429: deterministici
    o quota). Backoff lineare crescente tra i tentativi."""
    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, **kwargs)
            if resp.status_code in _RETRY_STATUSES and attempt < retries:
                attempt += 1
                await asyncio.sleep(backoff * attempt)
                continue
            return resp
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= retries:
                raise
            attempt += 1
            await asyncio.sleep(backoff * attempt)


async def crtsh_lookup(domain: str) -> dict:
    """Riassunto dei certificati TLS pubblici per un dominio (log Certificate
    Transparency). {"ok": True, "cert_count": int, "subdomains": list[str],
    "latest_issuer": str | None} oppure {"ok": False, "error": str}."""
    url = f"https://crt.sh/?q={domain}&output=json"
    try:
        resp = await _get_with_retry(url)
        if resp.status_code == 404:
            # crt.sh usa 404 (non 200+[]) per "nessun certificato trovato":
            # è un risultato valido, non un errore di rete/servizio.
            return {"ok": True, "cert_count": 0, "subdomains": [], "latest_issuer": None}
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "crt.sh")}
    if not isinstance(data, list):
        return {"ok": False, "error": "risposta inattesa da crt.sh"}
    subdomains: set[str] = set()
    latest_issuer = None
    latest_not_before = None
    for entry in data:
        names = (entry.get("name_value") or "").split("\n")
        subdomains.update(n.strip() for n in names if n.strip())
        nb = entry.get("not_before")
        if nb and (latest_not_before is None or nb > latest_not_before):
            latest_not_before = nb
            latest_issuer = entry.get("issuer_name")
    return {
        "ok": True,
        "cert_count": len(data),
        "subdomains": sorted(subdomains)[:20],
        "latest_issuer": latest_issuer,
    }


async def nvd_lookup(cve_id: str) -> dict:
    """Riassunto di una CVE dal database ufficiale NVD (NIST). {"ok": True,
    "description": str | None, "cvss_score": float | None, "cvss_severity":
    str | None, "published": str | None} oppure {"ok": False, "error": str}."""
    # Endpoint API 2.0: /rest/json/cves/2.0 (plurale "cves"). Il vecchio
    # singolare /cve/2.0 è stato dismesso e ora risponde 404.
    url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "NVD")}
    vulns = data.get("vulnerabilities") or []
    if not vulns:
        # Query riuscita, zero risultati: nessun record per questa CVE,
        # non un errore di rete/servizio.
        return {
            "ok": True, "description": "Nessun record trovato per questa CVE.",
            "cvss_score": None, "cvss_severity": None, "published": None,
        }
    cve = vulns[0].get("cve", {})
    description = next(
        (d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"),
        None,
    )
    metrics = cve.get("metrics", {})
    cvss_score = None
    cvss_severity = None
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key)
        if entries:
            cvss_data = entries[0].get("cvssData", {})
            cvss_score = cvss_data.get("baseScore")
            cvss_severity = cvss_data.get("baseSeverity") or entries[0].get("baseSeverity")
            break
    return {
        "ok": True,
        "description": description,
        "cvss_score": cvss_score,
        "cvss_severity": cvss_severity,
        "published": cve.get("published"),
    }


async def urlscan_lookup(value: str, kind: str) -> dict:
    """Scan storici pubblici (urlscan.io) per un dominio, URL o IP. Solo
    l'endpoint di ricerca è keyless (la submission di nuove scansioni richiede
    API key, qui non usata). kind: "domain" | "url" | "ip". {"ok": True,
    "total": int, "scans": [{"page_url", "ip", "asn", "date", "result_url"},
    ...]} oppure {"ok": False, "error": str}. result_url punta alla pagina
    pubblica del report (non l'endpoint JSON), costruita dallo scan id (_id)."""
    if kind == "url":
        query = f'page.url:"{value}"'
    elif kind == "ip":
        query = f"ip:{value}"
    else:
        query = f"domain:{value}"
    url = f"https://urlscan.io/api/v1/search/?q={quote(query)}&size=10"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "urlscan.io")}
    results = data.get("results") or []
    scans = []
    for r in results[:10]:
        page = r.get("page") or {}
        scan_id = r.get("_id")
        scans.append({
            "page_url": page.get("url"),
            "ip": page.get("ip"),
            "asn": page.get("asn"),
            "date": (r.get("task") or {}).get("time"),
            "result_url": f"https://urlscan.io/result/{scan_id}/" if scan_id else None,
        })
    return {"ok": True, "total": data.get("total", len(scans)), "scans": scans}


async def cymru_asn_lookup(ip: str) -> dict:
    """ASN/organizzazione per un IP pubblico via whois.cymru.com (protocollo
    whois classico, porta 43, nessuna API key — nessun endpoint HTTP esiste
    per questo servizio). {"ok": True, "asn": str | None, "as_name": str | None,
    "country": str | None, "bgp_prefix": str | None, "registry": str | None,
    "allocated": str | None, "note": str | None} oppure {"ok": False, "error": str}
    (quest'ultimo solo per guasti di rete/protocollo, non per "IP non
    annunciato in BGP" — quello è un risultato valido, vedi "NA" sotto)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("whois.cymru.com", 43), timeout=_TIMEOUT
        )
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    try:
        writer.write(f" -v {ip}\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), timeout=_TIMEOUT)
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    finally:
        writer.close()
    lines = [ln.strip() for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()]
    if len(lines) < 2:
        return {"ok": False, "error": "risposta vuota da whois.cymru.com"}
    fields = [f.strip() for f in lines[1].split("|")]
    if len(fields) < 7:
        return {"ok": False, "error": "risposta malformata da whois.cymru.com"}
    if fields[0].upper() == "NA":
        # Risposta valida, IP semplicemente non annunciato nelle tabelle
        # BGP pubbliche (es. IP privato/riservato/non instradato): nessun
        # record, non un errore.
        return {
            "ok": True, "asn": None, "as_name": None, "country": None,
            "bgp_prefix": None, "registry": None, "allocated": None,
            "note": "IP non annunciato nelle tabelle BGP pubbliche.",
        }
    return {
        "ok": True,
        "asn": fields[0],
        "bgp_prefix": fields[2],
        "country": fields[3],
        "registry": fields[4],
        "allocated": fields[5],
        "as_name": fields[6],
        "note": None,
    }


async def abuseipdb_lookup(ip: str) -> dict:
    """Abuse confidence score per un IP via AbuseIPDB (richiede API key in
    ABUSEIPDB_API_KEY — vedi .env.example). Se la key non è configurata,
    ritorna {"ok": False} senza tentare la chiamata: il chiamante deve
    trattarlo come "non disponibile", non come errore di rete. {"ok": True,
    "abuse_score": int, "total_reports": int, "country": str, "isp": str,
    "domain": str, "last_reported": str | None, "is_whitelisted": bool}
    oppure {"ok": False, "error": str}."""
    api_key = os.environ.get("ABUSEIPDB_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ABUSEIPDB_API_KEY non configurata"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": api_key, "Accept": "application/json"},
            )
        resp.raise_for_status()
        data = resp.json().get("data", {})
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "AbuseIPDB")}
    return {
        "ok": True,
        "abuse_score": data.get("abuseConfidenceScore"),
        "total_reports": data.get("totalReports"),
        "country": data.get("countryCode"),
        "isp": data.get("isp"),
        "domain": data.get("domain"),
        "last_reported": data.get("lastReportedAt"),
        "is_whitelisted": data.get("isWhitelisted"),
        "usage_type": data.get("usageType"),
        "is_tor": data.get("isTor"),
        "num_distinct_users": data.get("numDistinctUsers"),
    }


def _virustotal_object_url(value: str) -> str:
    """Sceglie l'endpoint oggetto VT v3 in base alla FORMA del valore (nessun
    IOC type esplicito arriva dalla route, solo il valore grezzo): hash esa ->
    files, IPv4 -> ip_addresses, dominio nudo (no schema/path) -> domains,
    tutto il resto (contiene schema o path -> è un URL vero) -> urls."""
    if _HASH_RE.match(value):
        return f"https://www.virustotal.com/api/v3/files/{value}"
    if _IPV4_RE.match(value):
        return f"https://www.virustotal.com/api/v3/ip_addresses/{value}"
    if _BARE_DOMAIN_RE.match(value):
        return f"https://www.virustotal.com/api/v3/domains/{value}"
    resource_id = base64.urlsafe_b64encode(value.encode()).decode().strip("=")
    return f"https://www.virustotal.com/api/v3/urls/{resource_id}"


async def virustotal_lookup(value: str) -> dict:
    """Verdetto multi-motore (VirusTotal API v3) per hash, URL, IPv4 o
    dominio — stesso resource id nel catalogo per tutti e 4, distinti qui in
    base alla forma del valore (vedi _virustotal_object_url). Richiede API key
    in VIRUSTOTAL_API_KEY (vedi .env.example). {"ok": True, "malicious": int,
    "suspicious": int, "harmless": int, "undetected": int,
    "reputation": int | None, "last_analysis_date": str | None,
    "meaningful_name": str | None, "categories": str | None,
    "threat_label": str | None, "type_description": str | None,
    "tags": str | None, "times_submitted": int | None,
    "last_final_url": str | None, "title": str | None,
    "threat_names": str | None, "as_owner": str | None, "asn": int | None,
    "country": str | None, "registrar": str | None,
    "creation_date": str | None, "last_dns_records": str | None} oppure
    {"ok": False, "error": str}."""
    api_key = os.environ.get("VIRUSTOTAL_API_KEY")
    if not api_key:
        return {"ok": False, "error": "VIRUSTOTAL_API_KEY non configurata"}
    url = _virustotal_object_url(value)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers={"x-apikey": api_key})
        if resp.status_code == 404:
            # VT usa 404 quando l'IOC non è mai stato analizzato (l'oggetto non
            # esiste): risultato valido "non presente", non un errore.
            return {"ok": True, "found": False}
        resp.raise_for_status()
        attrs = resp.json().get("data", {}).get("attributes", {})
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "VirusTotal")}
    stats = attrs.get("last_analysis_stats") or {}
    last_analysis = attrs.get("last_analysis_date")
    categories = attrs.get("categories") or {}
    threat_class = attrs.get("popular_threat_classification") or {}
    tags = attrs.get("tags") or []
    threat_names = attrs.get("threat_names") or []
    creation_date = attrs.get("creation_date")
    dns_records = attrs.get("last_dns_records") or []
    return {
        "ok": True,
        "found": True,
        "malicious": stats.get("malicious"),
        "suspicious": stats.get("suspicious"),
        "harmless": stats.get("harmless"),
        "undetected": stats.get("undetected"),
        "reputation": attrs.get("reputation"),
        "last_analysis_date": (
            datetime.fromtimestamp(last_analysis, tz=timezone.utc).isoformat()
            if isinstance(last_analysis, (int, float)) else None
        ),
        "meaningful_name": attrs.get("meaningful_name"),
        "categories": ", ".join(sorted(set(categories.values()))) if categories else None,
        # famiglia malware suggerita dalla community — il campo più prezioso per un file
        "threat_label": threat_class.get("suggested_threat_label"),
        "type_description": attrs.get("type_description"),
        # dedup mantenendo l'ordine
        "tags": ", ".join(dict.fromkeys(tags)) if tags else None,
        "times_submitted": attrs.get("times_submitted"),
        # specifici URL (None sui file)
        "last_final_url": attrs.get("last_final_url"),
        "title": attrs.get("title"),
        "threat_names": ", ".join(threat_names) if threat_names else None,
        # specifici IP (None su file/url/dominio)
        "as_owner": attrs.get("as_owner"),
        "asn": attrs.get("asn"),
        "country": attrs.get("country"),
        # specifici dominio (None su file/url/IP)
        "registrar": attrs.get("registrar"),
        "creation_date": (
            datetime.fromtimestamp(creation_date, tz=timezone.utc).isoformat()
            if isinstance(creation_date, (int, float)) else None
        ),
        "last_dns_records": (
            ", ".join(f"{r.get('type')} {r.get('value')}" for r in dns_records[:5])
            if dns_records else None
        ),
    }


async def _shodan_internetdb(ip: str, client: httpx.AsyncClient) -> dict:
    """InternetDB: servizio gratuito di Shodan (nessuna key, nessun credito,
    nessuna membership). Fonte affidabile per il tier free, dove /shodan/host
    dà 403. 404 = IP non nel dataset = nessun servizio esposto (ok:True, liste
    vuote), non un errore. org/isp/os non sono disponibili qui."""
    resp = await client.get(f"https://internetdb.shodan.io/{ip}")
    if resp.status_code == 404:
        return {
            "ok": True, "ports": [], "hostnames": [], "org": None, "isp": None,
            "os": None, "vulns": [], "products": [], "tags": [],
        }
    resp.raise_for_status()
    data = resp.json()
    return {
        "ok": True,
        "ports": sorted(data.get("ports") or []),
        "hostnames": data.get("hostnames") or [],
        "org": None, "isp": None, "os": None,
        "vulns": sorted(data.get("vulns") or []),
        "products": data.get("cpes") or [],   # i CPE sono l'info prodotto disponibile qui
        "tags": data.get("tags") or [],
    }


async def shodan_lookup(ip: str) -> dict:
    """Dispositivi/servizi esposti su Internet per un IP. Risorsa KEYLESS in
    POE: InternetDB (gratuito, senza key) è la fonte base, così la scheda
    funziona sempre. Se SHODAN_API_KEY è configurata prova prima
    /shodan/host/{ip} (dati più ricchi: org/isp/os/banner), che però richiede
    una membership a pagamento — sul tier free dà 403: in quel caso (o su
    qualsiasi errore host) ricade su InternetDB. {"ok": True, "ports": list[int],
    "hostnames": list[str], "org": str|None, "isp": str|None, "os": str|None,
    "vulns": list[str], "products": list[str], "tags": list[str]} oppure
    {"ok": False, "error": str}."""
    api_key = os.environ.get("SHODAN_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if not api_key:
                # Nessuna key: InternetDB gratuito (Shodan è keyless in POE).
                return await _shodan_internetdb(ip, client)
            try:
                resp = await client.get(
                    f"https://api.shodan.io/shodan/host/{ip}",
                    params={"key": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError:
                # 403 (tier free) o qualsiasi guasto dell'host endpoint:
                # ricade su InternetDB gratuito, non fa fallire la scheda.
                return await _shodan_internetdb(ip, client)
            services = data.get("data") or []
            products = sorted({s["product"] for s in services if s.get("product")})
            return {
                "ok": True,
                "ports": sorted(data.get("ports") or []),
                "hostnames": data.get("hostnames") or [],
                "org": data.get("org"),
                "isp": data.get("isp"),
                "os": data.get("os"),
                "vulns": sorted(data.get("vulns") or []),
                "products": products,
                "tags": sorted(data.get("tags") or []),
            }
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Shodan")}


# ── Persone: email / telefono (keyless, o locale offline) ────────────────────

async def gravatar_lookup(email: str) -> dict:
    """Profilo pubblico Gravatar per un'email (keyless): rivela SOLO ciò che il
    titolare ha reso pubblico (nome, account social collegati). Hash MD5
    dell'email normalizzata (lowercase + trim). 404 = nessun profilo (risultato
    valido, non errore). {"ok": True, "has_profile": bool, "display_name": str
    | None, "accounts": str | None, "location": str | None, "profile_url": str
    | None} oppure {"ok": False, "error": str}."""
    # MD5 imposto dall'API Gravatar come identificatore dell'email: non e' un
    # uso crittografico. `usedforsecurity=False` lo dichiara (e chiude il
    # finding High di bandit B324, che altrimenti nasconde i problemi veri).
    h = hashlib.md5(email.strip().lower().encode("utf-8"), usedforsecurity=False).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(f"https://gravatar.com/{h}.json",
                                    headers={"User-Agent": "POE-OSINT"})
        if resp.status_code == 404:
            return {"ok": True, "has_profile": False, "display_name": None,
                    "accounts": None, "location": None, "profile_url": None}
        resp.raise_for_status()
        entry = (resp.json().get("entry") or [{}])[0]
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Gravatar")}
    accounts = [a.get("shortname") or a.get("domain")
                for a in (entry.get("accounts") or []) if a.get("shortname") or a.get("domain")]
    return {
        "ok": True,
        "has_profile": True,
        "display_name": entry.get("displayName") or entry.get("preferredUsername"),
        "accounts": ", ".join(accounts) or None,
        "location": entry.get("currentLocation") or None,
        "profile_url": entry.get("profileUrl"),
    }


async def xposedornot_lookup(email: str) -> dict:
    """Data-breach pubblici in cui compare un'email (XposedOrNot, keyless) —
    uso difensivo/OSINT. 404 = nessun breach noto (risultato valido). {"ok":
    True, "breached": bool, "breach_count": int, "breaches": str | None} oppure
    {"ok": False, "error": str}."""
    url = f"https://api.xposedornot.com/v1/check-email/{quote(email)}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": "POE-OSINT"})
        if resp.status_code == 404:
            return {"ok": True, "breached": False, "breach_count": 0, "breaches": None}
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "XposedOrNot")}
    raw = data.get("breaches")
    breaches = raw[0] if (isinstance(raw, list) and raw and isinstance(raw[0], list)) else []
    return {
        "ok": True,
        "breached": bool(breaches),
        "breach_count": len(breaches),
        "breaches": ", ".join(breaches[:15]) or None,
    }


_PHONE_TYPE_LABELS = {
    phonenumbers.PhoneNumberType.MOBILE: "mobile",
    phonenumbers.PhoneNumberType.FIXED_LINE: "fisso",
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fisso o mobile",
    phonenumbers.PhoneNumberType.TOLL_FREE: "numero verde",
    phonenumbers.PhoneNumberType.PREMIUM_RATE: "a pagamento",
    phonenumbers.PhoneNumberType.VOIP: "VoIP",
}


async def phone_info_lookup(phone: str) -> dict:
    """Metadati di un numero di telefono (LOCALE, offline, nessuna rete/API):
    validità, regione geografica, operatore, tipo linea, prefisso paese —
    tramite la libreria phonenumbers. {"ok": True, "valid": bool, "region": str
    | None, "carrier": str | None, "line_type": str | None, "country_code": str
    | None} oppure {"ok": False, "error": str} se il numero non è parsabile
    (serve il prefisso internazionale, es. +39)."""
    try:
        num = phonenumbers.parse(phone, None)
    except Exception:
        return {"ok": False, "error": "numero non parsabile (serve il prefisso internazionale, es. +39)"}
    if not phonenumbers.is_valid_number(num):
        return {"ok": True, "valid": False, "region": None, "carrier": None,
                "line_type": None, "country_code": f"+{num.country_code}"}
    return {
        "ok": True,
        "valid": True,
        "region": geocoder.description_for_number(num, "it") or None,
        "carrier": carrier.name_for_number(num, "it") or None,
        "line_type": _PHONE_TYPE_LABELS.get(phonenumbers.number_type(num), "sconosciuto"),
        "country_code": f"+{num.country_code}",
    }


# ── Codice Fiscale italiano: reverse deterministico LOCALE (offline) ──────────
# Il CF codifica sesso, data e comune di nascita in modo reversibile. Tabelle
# ufficiali (mese, calcolo carattere di controllo). Belfiore: subset curato dei
# comuni maggiori + estero; per i codici non in tabella si mostra il codice
# catastale grezzo (l'analista lo risolve). Espandibile con la tabella completa.
_CF_RE = re.compile(r"^[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]$")
_CF_MONTHS = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "H": 6,
              "L": 7, "M": 8, "P": 9, "R": 10, "S": 11, "T": 12}
_CF_ODD = {c: v for c, v in zip(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21,
     2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23])}
_CF_EVEN = {c: (int(c) if c.isdigit() else "ABCDEFGHIJKLMNOPQRSTUVWXYZ".index(c))
            for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_BELFIORE = {
    "H501": "Roma", "F205": "Milano", "F839": "Napoli", "L219": "Torino",
    "D969": "Genova", "A944": "Bologna", "D612": "Firenze", "G273": "Palermo",
    "L736": "Venezia", "L781": "Verona", "A662": "Bari", "C351": "Catania",
    "G224": "Padova", "L424": "Trieste", "B157": "Brescia",
}


def _cf_check_char(body15: str) -> str:
    total = sum(_CF_ODD[ch] if i % 2 == 0 else _CF_EVEN[ch] for i, ch in enumerate(body15))
    return chr(ord("A") + total % 26)


async def codice_fiscale_lookup(cf: str) -> dict:
    """Reverse LOCALE (offline, nessuna rete) di un Codice Fiscale italiano:
    sesso, data di nascita, comune (o codice catastale) e validità del carattere
    di controllo. {"ok": True, "valido": bool, "sesso": str, "data_nascita": str,
    "comune": str, "codice_catastale": str} oppure {"ok": False, "error": str}
    se il formato non è un CF."""
    cf = (cf or "").strip().upper().replace(" ", "")
    if not _CF_RE.match(cf):
        return {"ok": False, "error": "non è un codice fiscale valido (formato)"}
    valido = _cf_check_char(cf[:15]) == cf[15]
    year2, month, day = int(cf[6:8]), _CF_MONTHS[cf[8]], int(cf[9:11])
    sesso = "femmina" if day > 40 else "maschio"
    if day > 40:
        day -= 40
    # Il CF non porta il secolo: euristica 1900/2000 (invertibile solo in parte).
    year = 2000 + year2 if (2000 + year2) <= datetime.now(timezone.utc).year else 1900 + year2
    belfiore = cf[11:15]
    if belfiore.startswith("Z"):
        comune = "nato all'estero (codice Z)"
    else:
        comune = _BELFIORE.get(belfiore) or f"codice catastale {belfiore} (comune non in tabella locale)"
    return {
        "ok": True,
        "valido": valido,
        "sesso": sesso,
        "data_nascita": f"{day:02d}/{month:02d}/{year}",
        "comune": comune,
        "codice_catastale": belfiore,
    }


# ── Google Dork mirati per tipo di IOC (LOCALE: costruisce solo query/URL,
#    nessuna rete). Template deterministici; l'utente apre i link su Google. ────
_DORK_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "email": [
        ("Menzioni esatte", '"{v}"'),
        ("Leak / paste / codice", 'intext:"{v}" (site:pastebin.com OR site:github.com OR site:gist.github.com)'),
        ("Documenti", '"{v}" (filetype:pdf OR filetype:xlsx OR filetype:csv OR filetype:txt)'),
        ("Social", '"{v}" (site:linkedin.com OR site:facebook.com OR site:twitter.com)'),
    ],
    "person_name": [
        ("Social", '"{v}" (site:linkedin.com OR site:facebook.com OR site:instagram.com)'),
        ("CV / curriculum", '"{v}" (curriculum OR cv OR resume) filetype:pdf'),
        ("Contatti", '"{v}" (email OR "@" OR telefono OR tel)'),
    ],
    "username": [
        ("Piattaforme", '"{v}" (site:github.com OR site:reddit.com OR site:twitter.com OR site:instagram.com)'),
        ("Menzioni", 'intext:"{v}"'),
        ("Forum / paste", '"{v}" (site:pastebin.com OR forum OR board)'),
    ],
    "social_handle": [
        ("Piattaforme", '"{v}" (site:twitter.com OR site:instagram.com OR site:tiktok.com)'),
        ("Menzioni", 'intext:"{v}"'),
    ],
    "phone": [
        ("Menzioni esatte", '"{v}"'),
        ("Annunci / social", '"{v}" (site:facebook.com OR annunci OR marketplace)'),
    ],
    "domain": [
        ("Pagine indicizzate", 'site:{v}'),
        ("File esposti", 'site:{v} (filetype:pdf OR filetype:xlsx OR filetype:log OR filetype:sql OR filetype:env)'),
        ("Pannelli / login / index", 'site:{v} (intitle:"index of" OR inurl:admin OR inurl:login OR inurl:.git)'),
        ("Menzioni altrove", '"{v}" -site:{v}'),
    ],
    "ipv4": [
        ("Menzioni esatte", '"{v}"'),
        ("Leak / paste", '"{v}" (site:pastebin.com OR site:github.com)'),
    ],
}


async def dorks_lookup(value: str, kind: str) -> dict:
    """Genera Google Dork mirati per il tipo di IOC (LOCALE, nessuna rete: solo
    costruzione di query e URL). {"ok": True, "dorks": [{"label", "query",
    "url"}, ...]}. url è già pronto per Google (query url-encoded)."""
    templates = _DORK_TEMPLATES.get(kind) or [("Menzioni esatte", '"{v}"')]
    dorks = []
    for label, tmpl in templates:
        query = tmpl.replace("{v}", value)
        dorks.append({
            "label": label,
            "query": query,
            "url": f"https://www.google.com/search?q={quote(query)}",
        })
    return {"ok": True, "dorks": dorks}


# ── Threat-intel a chiave gratuita (abuse.ch ThreatFox/URLhaus, AlienVault OTX,
#    Hunter.io). Key da .env (ABUSECH_API_KEY/OTX_API_KEY/HUNTER_API_KEY). ──────

# abuse.ch risponde 403 + {"query_status":"unknown_auth_key"} quando la Auth-Key
# non è registrata. Le key sono GRATUITE: si generano sul portale account.
# La stessa Auth-Key vale per ThreatFox, URLhaus e MalwareBazaar: se viene
# rifiutata qui, e' rifiutata ovunque. I due modi piu' comuni di sbagliarla sono
# copiare dal portale un valore che non e' l'Auth-Key, e rigenerarla dopo averla
# incollata (rigenerare invalida la precedente). Il messaggio li nomina entrambi:
# senza, si finisce a incollare piu' volte la stessa chiave sbagliata.
_ABUSECH_BAD_KEY = (
    "Auth-Key abuse.ch non riconosciuta. Su auth.abuse.ch (registrazione "
    "gratuita) apri il tuo profilo e copia il campo Auth-Key — non l'ID utente "
    "ne' una vecchia API key. Se l'hai rigenerata dopo averla incollata, quella "
    "in POE non vale piu'. Verifica anche di aver confermato l'email. "
    "La stessa chiave vale per ThreatFox, URLhaus e MalwareBazaar."
)

async def threatfox_lookup(value: str) -> dict:
    """abuse.ch ThreatFox: attribuzione a famiglia malware di un IOC (IP,
    dominio, URL, hash). Richiede ABUSECH_API_KEY (gratuita su auth.abuse.ch,
    header Auth-Key). {"ok": True, "found": bool, "malware": str | None,
    "threat_type": str | None, "confidence": int | None, "first_seen": str |
    None, "tags": str | None} oppure {"ok": False, "error": str}."""
    api_key = os.environ.get("ABUSECH_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ABUSECH_API_KEY non configurata"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://threatfox-api.abuse.ch/api/v1/",
                json={"query": "search_ioc", "search_term": value},
                headers={"Auth-Key": api_key},
            )
        data = resp.json()
        # abuse.ch: Auth-Key non registrata → 403 + query_status unknown_auth_key.
        # Messaggio esplicito (non è un "piano a pagamento": le key sono gratuite).
        if isinstance(data, dict) and data.get("query_status") == "unknown_auth_key":
            return {"ok": False, "error": _ABUSECH_BAD_KEY}
        resp.raise_for_status()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "ThreatFox")}
    rows = data.get("data") or []
    if data.get("query_status") != "ok" or not isinstance(rows, list) or not rows:
        return {"ok": True, "found": False, "malware": None, "threat_type": None,
                "confidence": None, "first_seen": None, "tags": None}
    row = rows[0]
    tags = row.get("tags") or []
    return {
        "ok": True,
        "found": True,
        "malware": row.get("malware_printable") or row.get("malware"),
        "threat_type": row.get("threat_type"),
        "confidence": row.get("confidence_level"),
        "first_seen": row.get("first_seen"),
        "tags": ", ".join(tags) if tags else None,
    }


async def urlhaus_lookup(value: str) -> dict:
    """abuse.ch URLhaus: URL malevoli noti associati a un host (dominio/IP) o
    verdetto su un URL specifico. Endpoint scelto dalla forma del valore.
    Richiede ABUSECH_API_KEY (header Auth-Key). {"ok": True, "found": bool,
    "threat": str | None, "status": str | None, "url_count": int | None,
    "tags": str | None, "blacklists": str | None} oppure {"ok": False,
    "error": str}."""
    api_key = os.environ.get("ABUSECH_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ABUSECH_API_KEY non configurata"}
    is_url = "://" in value or value.startswith("http")
    endpoint = "https://urlhaus-api.abuse.ch/v1/url/" if is_url else "https://urlhaus-api.abuse.ch/v1/host/"
    payload = {"url": value} if is_url else {"host": value}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(endpoint, data=payload, headers={"Auth-Key": api_key})
        data = resp.json()
        if isinstance(data, dict) and data.get("query_status") == "unknown_auth_key":
            return {"ok": False, "error": _ABUSECH_BAD_KEY}
        resp.raise_for_status()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "URLhaus")}
    if data.get("query_status") not in ("ok",):
        return {"ok": True, "found": False, "threat": None, "status": None,
                "url_count": None, "tags": None, "blacklists": None}
    tags = data.get("tags") or []
    bl = data.get("blacklists") or {}
    return {
        "ok": True,
        "found": True,
        "threat": data.get("threat"),
        "status": data.get("url_status"),
        "url_count": int(data["url_count"]) if str(data.get("url_count") or "").isdigit() else None,
        "tags": ", ".join(tags) if tags else None,
        "blacklists": ", ".join(f"{k}:{v}" for k, v in bl.items()) or None,
    }


def _otx_indicator_path(value: str) -> str | None:
    """Sezione /indicators/{type}/{value}/general di OTX in base alla forma del
    valore (nessun IOC type esplicito dalla route). None se non riconosciuto."""
    if _CVE_RE.match(value):
        return f"cve/{value}"
    if _HASH_RE.match(value):
        return f"file/{value}"
    if _IPV4_RE.match(value):
        return f"IPv4/{value}"
    if "://" in value:
        return f"url/{quote(value, safe='')}"
    if _BARE_DOMAIN_RE.match(value):
        return f"domain/{value}"
    return None


async def otx_lookup(value: str) -> dict:
    """AlienVault OTX: pulse di threat-intel community per un IOC (IP, dominio,
    URL, hash, CVE). Una sola key copre tutti i tipi (OTX_API_KEY, gratuita,
    header X-OTX-API-KEY). {"ok": True, "pulse_count": int, "pulses": str |
    None, "malware_families": str | None, "tags": str | None} oppure {"ok":
    False, "error": str}."""
    api_key = os.environ.get("OTX_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OTX_API_KEY non configurata"}
    path = _otx_indicator_path(value)
    if path is None:
        return {"ok": False, "error": "tipo IOC non supportato da OTX"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://otx.alienvault.com/api/v1/indicators/{path}/general",
                headers={"X-OTX-API-KEY": api_key},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "AlienVault OTX")}
    pulse_info = data.get("pulse_info") or {}
    pulses = pulse_info.get("pulses") or []
    names = [p.get("name") for p in pulses if p.get("name")]
    families: set[str] = set()
    tags: set[str] = set()
    for p in pulses:
        for fam in (p.get("malware_families") or []):
            families.add(fam.get("display_name") or fam.get("id") if isinstance(fam, dict) else str(fam))
        for t in (p.get("tags") or []):
            tags.add(t)
    return {
        "ok": True,
        "pulse_count": pulse_info.get("count", len(pulses)),
        "pulses": ", ".join(names[:6]) or None,
        "malware_families": ", ".join(sorted(f for f in families if f)) or None,
        "tags": ", ".join(sorted(tags)[:10]) or None,
    }


async def hunter_verify_lookup(email: str) -> dict:
    """Hunter.io email-verifier: deliverability di un'email (valida/rischiosa/
    non recapitabile, disposable, webmail, score). Richiede HUNTER_API_KEY
    (gratuita, query param api_key). {"ok": True, "status": str | None,
    "result": str | None, "score": int | None, "disposable": bool | None,
    "webmail": bool | None} oppure {"ok": False, "error": str}."""
    api_key = os.environ.get("HUNTER_API_KEY")
    if not api_key:
        return {"ok": False, "error": "HUNTER_API_KEY non configurata"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/email-verifier",
                params={"email": email, "api_key": api_key},
            )
        resp.raise_for_status()
        d = (resp.json().get("data") or {})
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Hunter")}
    return {
        "ok": True,
        "status": d.get("status"),
        "result": d.get("result"),
        "score": d.get("score"),
        "disposable": d.get("disposable"),
        "webmail": d.get("webmail"),
    }


# ── Test key: verifica ON-DEMAND (mai automatica, mai a polling) che una key
# funzioni davvero. Usate solo dal bottone "Test" nella pagina Servizi & API —
# una singola query esplicita al click dell'operatore, non nella status bar
# (che pinga il sito pubblico, non l'API, per non consumare quota). ──────────

async def test_abuseipdb_key(api_key: str) -> dict:
    """{"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": "8.8.8.8", "maxAgeInDays": 1},
                headers={"Key": api_key, "Accept": "application/json"},
            )
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code == 200:
        return {"ok": True, "detail": "chiave valida"}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


async def test_virustotal_key(api_key: str) -> dict:
    """200 o 404 = autenticazione riuscita (l'hash sonda non deve esistere
    davvero su VT, serve solo a verificare la key). {"ok": True, "detail": str}
    oppure {"ok": False, "error": str}."""
    probe_hash = "aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://www.virustotal.com/api/v3/files/{probe_hash}",
                headers={"x-apikey": api_key},
            )
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code in (200, 404):
        return {"ok": True, "detail": "chiave valida"}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    if resp.status_code == 429:
        return {"ok": False, "error": "quota esaurita"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


async def test_shodan_key(api_key: str) -> dict:
    """Usa /api-info, l'endpoint dedicato di Shodan per verificare una key
    senza consumare query credit. {"ok": True, "detail": str} oppure
    {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://api.shodan.io/api-info", params={"key": api_key})
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code == 200:
        data = resp.json()
        return {
            "ok": True,
            "detail": f"piano {data.get('plan', '?')}, {data.get('query_credits', '?')} query credits",
        }
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


async def test_abusech_key(api_key: str) -> dict:
    """Verifica la Auth-Key abuse.ch (ThreatFox/URLhaus) con una query di ricerca
    minima. {"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://threatfox-api.abuse.ch/api/v1/",
                json={"query": "search_ioc", "search_term": "1.1.1.1"},
                headers={"Auth-Key": api_key},
            )
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code == 200:
        return {"ok": True, "detail": "chiave valida"}
    # Il pannello e' il posto dove si sta CONFIGURANDO la chiave: qui il
    # messaggio deve essere almeno esplicito quanto quello del lookup, non meno.
    try:
        if resp.json().get("query_status") == "unknown_auth_key":
            return {"ok": False, "error": _ABUSECH_BAD_KEY}
    except (ValueError, AttributeError):
        pass
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


async def test_otx_key(api_key: str) -> dict:
    """Verifica la key OTX via /user/me (nessun consumo di quota IOC).
    {"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://otx.alienvault.com/api/v1/user/me",
                                    headers={"X-OTX-API-KEY": api_key})
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code == 200:
        return {"ok": True, "detail": "chiave valida"}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


async def test_hunter_key(api_key: str) -> dict:
    """Verifica la key Hunter via /account (nessun consumo di crediti verify).
    {"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://api.hunter.io/v2/account", params={"api_key": api_key})
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code == 200:
        return {"ok": True, "detail": "chiave valida"}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "chiave non valida"}
    return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}


# ── Batch persone (Wave A): fonti live keyless per email/username ─────────────

async def emailrep_lookup(email: str) -> dict:
    """Reputation di un'email (EmailRep.io, keyless; EMAILREP_API_KEY opzionale
    alza il rate limit via header Key). {"ok": True, "reputation": str, ...}
    oppure {"ok": False, "error": str}."""
    headers = {"User-Agent": "POE-OSINT"}
    key = os.environ.get("EMAILREP_API_KEY")
    if key:
        headers["Key"] = key
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"https://emailrep.io/{quote(email)}", headers=headers)
        if resp.status_code == 429:
            return {"ok": False, "error": "EmailRep: limite richieste raggiunto "
                    "(configura EMAILREP_API_KEY per alzarlo)"}
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "EmailRep")}
    details = data.get("details") or {}
    return {
        "ok": True,
        "reputation": data.get("reputation"),
        "suspicious": data.get("suspicious"),
        "references": data.get("references"),
        "blacklisted": details.get("blacklisted"),
        "malicious_activity": details.get("malicious_activity"),
        "credentials_leaked": details.get("credentials_leaked"),
        "data_breach": details.get("data_breach"),
        "last_seen": details.get("last_seen"),
        "profiles": ", ".join(details.get("profiles") or []) or None,
        "disposable": details.get("disposable"),
        "free_provider": details.get("free_provider"),
        "deliverable": details.get("deliverable"),
    }


async def hudsonrock_email_lookup(email: str) -> dict:
    """Hudson Rock Cavalier (keyless, gratis): l'email compare in infezioni da
    infostealer? {"ok": True, "compromised": bool, "stealer_count": int,
    "message": str | None, "stealers": str | None} oppure {"ok": False,
    "error": str}."""
    url = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params={"email": email},
                                    headers={"User-Agent": "POE-OSINT"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Hudson Rock")}
    stealers = data.get("stealers") or []
    return {
        "ok": True,
        "compromised": bool(stealers),
        "stealer_count": len(stealers),
        "message": data.get("message"),
        "stealers": "; ".join(
            f"{s.get('stealer_family', '?')} ({(s.get('date_compromised') or '')[:10]})"
            for s in stealers[:10]) or None,
    }


async def hudsonrock_username_lookup(username: str) -> dict:
    """Hudson Rock Cavalier (keyless): lo username compare in infezioni da
    infostealer? Stessa forma di hudsonrock_email_lookup."""
    url = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params={"username": username},
                                    headers={"User-Agent": "POE-OSINT"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Hudson Rock")}
    stealers = data.get("stealers") or []
    return {
        "ok": True,
        "compromised": bool(stealers),
        "stealer_count": len(stealers),
        "message": data.get("message"),
        "stealers": "; ".join(
            f"{s.get('stealer_family', '?')} ({(s.get('date_compromised') or '')[:10]})"
            for s in stealers[:10]) or None,
    }


async def github_api_lookup(username: str) -> dict:
    """Profilo pubblico GitHub via API (keyless, 60 req/h). {"ok": True,
    "found": bool, ...} oppure {"ok": False, "error": str}. 404 = utente
    inesistente (found=False)."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"https://api.github.com/users/{quote(username)}",
                                    headers={"User-Agent": "POE-OSINT",
                                             "Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return {"ok": True, "found": False}
        resp.raise_for_status()
        d = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "GitHub")}
    return {
        "ok": True, "found": True,
        "name": d.get("name"), "company": d.get("company"),
        "blog": d.get("blog") or None, "email": d.get("email"),
        "bio": d.get("bio"), "location": d.get("location"),
        "twitter": d.get("twitter_username"), "public_repos": d.get("public_repos"),
        "followers": d.get("followers"), "created_at": (d.get("created_at") or "")[:10] or None,
        "profile_url": d.get("html_url"),
    }


async def keybase_api_lookup(username: str) -> dict:
    """Keybase user lookup (keyless): prove d'identità cross-piattaforma
    (twitter/github/reddit/hn/...) e chiavi PGP di uno username. {"ok": True,
    "found": bool, ...} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://keybase.io/_/api/1.0/user/lookup.json",
                                    params={"usernames": username},
                                    headers={"User-Agent": "POE-OSINT"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Keybase")}
    them = data.get("them") or []
    if not them or not them[0]:
        return {"ok": True, "found": False}
    u = them[0]
    profile = u.get("profile") or {}
    proofs = ((u.get("proofs_summary") or {}).get("all")) or []
    accounts = [f"{p.get('proof_type')}:{p.get('nametag')}"
                for p in proofs if p.get("proof_type") and p.get("nametag")]
    pgp = (u.get("public_keys") or {}).get("pgp_public_keys") or []
    uname = (u.get("basics") or {}).get("username", username)
    return {
        "ok": True, "found": True,
        "full_name": profile.get("full_name"),
        "location": profile.get("location"),
        "accounts": ", ".join(accounts) or None,
        "pgp_keys": len(pgp) or None,
        "profile_url": f"https://keybase.io/{uname}",
    }


async def gitlab_api_lookup(username: str) -> dict:
    """Profilo pubblico GitLab.com via API (keyless). {"ok": True, "found":
    bool, ...} oppure {"ok": False, "error": str}. Lista vuota = inesistente."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://gitlab.com/api/v4/users",
                                    params={"username": username},
                                    headers={"User-Agent": "POE-OSINT"})
        resp.raise_for_status()
        arr = resp.json()
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "GitLab")}
    if not isinstance(arr, list) or not arr:
        return {"ok": True, "found": False}
    d = arr[0]
    return {
        "ok": True, "found": True,
        "name": d.get("name"), "state": d.get("state"),
        "bio": d.get("bio") or None, "location": d.get("location") or None,
        "website": d.get("website_url") or None, "twitter": d.get("twitter") or None,
        "linkedin": d.get("linkedin") or None,
        "created_at": (d.get("created_at") or "")[:10] or None,
        "profile_url": d.get("web_url"),
    }


async def reddit_api_lookup(username: str) -> dict:
    """Meta account Reddit via about.json (keyless, User-Agent obbligatorio).
    {"ok": True, "found": bool, ...} oppure {"ok": False, "error": str}.
    403/404 = inesistente/privato (found=False)."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"https://www.reddit.com/user/{quote(username)}/about.json",
                                    headers={"User-Agent": "POE-OSINT/1.0"})
        if resp.status_code in (403, 404):
            return {"ok": True, "found": False}
        resp.raise_for_status()
        d = (resp.json().get("data") or {})
    except Exception as exc:
        return {"ok": False, "error": _friendly_http_error(exc, "Reddit")}
    created = d.get("created_utc")
    created_str = (datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
                   if created else None)
    return {
        "ok": True, "found": True,
        "created": created_str,
        "link_karma": d.get("link_karma"),
        "comment_karma": d.get("comment_karma"),
        "verified": d.get("verified"),
        "is_mod": d.get("is_mod"),
        "profile_url": f"https://www.reddit.com/user/{d.get('name', username)}",
    }


# ── Batch persone (Wave B): fonti live key-gated per email/telefono ───────────
# (HIBP breach/paste rimosse: unico servizio del batch senza free tier —
# solo a pagamento, ~$4/mese — eliminato su richiesta esplicita.)


def _ipqs_error(data: dict) -> str:
    """IPQS risponde 200 + success:false e mette la causa in `message`.

    Prima si attribuiva sempre la colpa alla chiave: con un free tier da 35
    lookup al giorno, l'esaurimento del credito e' invece lo scenario piu'
    probabile, ed e' quello che veniva diagnosticato peggio. `message` non
    contiene la chiave, quindi e' sicuro mostrarlo. Il `request_id` e' quello
    che IPQS chiede di allegare all'assistenza: perderlo costa un altro giro."""
    msg = str(data.get("message") or "richiesta non riuscita").strip()
    rid = str(data.get("request_id") or "").strip()
    return f"IPQualityScore: {msg}" + (f" (request_id {rid})" if rid else "")


async def ipqs_email_lookup(email: str) -> dict:
    """IPQualityScore — fraud score e reputazione di un'email. Richiede
    IPQS_API_KEY (free tier). La key è nel path dell'URL: mai includerla in
    un messaggio d'errore. {"ok": True, "valid": bool, "disposable": bool,
    "deliverability": str | None, "fraud_score": int | None, "recent_abuse":
    bool | None, "leaked": bool | None, "first_seen": str | None} oppure
    {"ok": False, "error": str}."""
    api_key = os.environ.get("IPQS_API_KEY")
    if not api_key:
        return {"ok": False, "error": "IPQS_API_KEY non configurata"}
    url = f"https://ipqualityscore.com/api/json/email/{quote(api_key, safe='')}/{quote(email)}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "IPQualityScore: errore di rete o timeout"}
    if not data.get("success", True):
        return {"ok": False, "error": _ipqs_error(data)}
    first_seen = (data.get("first_seen") or {}).get("human")
    return {
        "ok": True,
        "valid": data.get("valid"),
        "disposable": data.get("disposable"),
        "deliverability": data.get("deliverability"),
        "fraud_score": data.get("fraud_score"),
        "recent_abuse": data.get("recent_abuse"),
        "leaked": data.get("leaked"),
        "first_seen": first_seen,
    }


async def ipqs_phone_lookup(phone: str) -> dict:
    """IPQualityScore — fraud score e validazione di un numero. Richiede
    IPQS_API_KEY (stessa key di ipqs_email_lookup). {"ok": True, "valid":
    bool, "active": bool | None, "fraud_score": int | None, "recent_abuse":
    bool | None, "line_type": str | None, "carrier": str | None, "leaked":
    bool | None, "risky": bool | None} oppure {"ok": False, "error": str}."""
    api_key = os.environ.get("IPQS_API_KEY")
    if not api_key:
        return {"ok": False, "error": "IPQS_API_KEY non configurata"}
    url = f"https://ipqualityscore.com/api/json/phone/{quote(api_key, safe='')}/{quote(phone)}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "IPQualityScore: errore di rete o timeout"}
    if not data.get("success", True):
        return {"ok": False, "error": _ipqs_error(data)}
    return {
        "ok": True,
        "valid": data.get("valid"),
        "active": data.get("active"),
        "fraud_score": data.get("fraud_score"),
        "recent_abuse": data.get("recent_abuse"),
        "line_type": data.get("line_type"),
        "carrier": data.get("carrier"),
        "leaked": data.get("leaked"),
        "risky": data.get("risky"),
    }


# Cause d'errore Numverify che richiedono azioni DIVERSE da parte dell'utente.
# `type` viene dallo spec ufficiale; `info` e' il testo umano del servizio, che
# si tiene comunque per non perdere i casi non mappati.
_NUMVERIFY_CAUSE = {
    "invalid_access_key": "chiave non valida — controlla NUMVERIFY_API_KEY",
    "missing_access_key": "chiave non valida — controlla NUMVERIFY_API_KEY",
    "inactive_user": "account non attivo: conferma la registrazione su numverify.com",
    "account_on_hold": "account sospeso da apilayer",
    "usage_limit_reached": "quota mensile esaurita (free tier: 100 richieste/mese)",
    "daily_usage_limit_reached": "quota giornaliera esaurita",
    "fair_use_limit_reached": "limite di fair use raggiunto",
    "rate_limit_reached": "troppe richieste ravvicinate: riprova fra poco",
    "https_access_restricted": "https non incluso nel piano Numverify in uso",
    "api_access_blocked": "accesso all'API bloccato da apilayer",
}


def _numverify_error(data: dict) -> str:
    err = data.get("error") or {}
    tipo = str(err.get("type") or "")
    causa = _NUMVERIFY_CAUSE.get(tipo)
    if causa:
        return f"Numverify: {causa}"
    info = err.get("info") or "richiesta non riuscita"
    return f"Numverify: {info}"


async def numverify_lookup(phone: str) -> dict:
    """Numverify — validazione e carrier di un numero. Richiede
    NUMVERIFY_API_KEY (free tier). {"ok": True, "valid": bool,
    "country_code": str | None, "location": str | None, "carrier": str |
    None, "line_type": str | None} oppure {"ok": False, "error": str}."""
    api_key = os.environ.get("NUMVERIFY_API_KEY")
    if not api_key:
        return {"ok": False, "error": "NUMVERIFY_API_KEY non configurata"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://apilayer.net/api/validate",
                                    params={"access_key": api_key, "number": phone})
    except Exception:
        return {"ok": False, "error": "Numverify: errore di rete o timeout"}
    # Numverify segnala gli errori con status HTTP VERI (401/403/429), non con
    # 200 + success:false. Chiamare raise_for_status() prima di leggere il corpo
    # faceva collassare sei cause diverse — chiave invalida, quota mensile
    # esaurita, rate limit, https fuori piano, account sospeso — in un unico
    # "errore di rete o timeout", che manda a cercare un guasto inesistente.
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False,
                "error": f"Numverify: risposta non leggibile (HTTP {resp.status_code})"}
    if isinstance(data, dict) and data.get("success") is False:
        return {"ok": False, "error": _numverify_error(data)}
    if resp.status_code != 200:
        return {"ok": False, "error": f"Numverify: risposta inattesa (HTTP {resp.status_code})"}
    return {
        "ok": True,
        "valid": data.get("valid"),
        "country_code": data.get("country_code") or None,
        "location": data.get("location") or None,
        "carrier": data.get("carrier") or None,
        "line_type": data.get("line_type") or None,
    }


async def whatsmyname_lookup(username: str) -> dict:
    """WhatsMyName (dataset locale, 719 siti): dove esiste un account con
    questo username. Checker async con concorrenza limitata; nessuna rete per
    caricare il dataset (solo per interrogare i singoli siti). ON-DEMAND (non
    auto-run: troppo lento per l'expand automatico della card). {"ok": True,
    "found": [{"name": str, "url": str}], "checked": int, "total_sites": int}
    oppure {"ok": False, "error": str}. Le richieste fallite (timeout, sito
    irraggiungibile, protezioni anti-bot) sono conteggiate in "checked" ma non
    bloccano il risultato complessivo — un sito non verificabile non è un
    errore fatale. ~21/719 siti reali richiedono POST (post_body/headers,
    uri_check senza {account}): saltati esplicitamente, non contano in
    "checked" (non ancora supportati da questo checker minimo)."""
    try:
        data = json.loads(_WMN_DATA_PATH.read_text(encoding="utf-8"))
        sites = data.get("sites") or []
    except Exception as exc:
        return {"ok": False, "error": f"dataset WhatsMyName non leggibile: {exc}"}
    if not sites:
        return {"ok": False, "error": "dataset WhatsMyName vuoto"}

    semaphore = asyncio.Semaphore(20)
    found: list[dict] = []
    checked = 0

    async def _check_one(site: dict, client: httpx.AsyncClient) -> None:
        nonlocal checked
        uri_template = site.get("uri_check")
        e_code = site.get("e_code")
        e_string = site.get("e_string") or ""
        name = site.get("name", "?")
        if not uri_template or "{account}" not in uri_template:
            return
        url = uri_template.replace("{account}", quote(username, safe=""))
        async with semaphore:
            try:
                resp = await client.get(url, timeout=5.0, headers={"User-Agent": "POE-OSINT"})
            except Exception:
                checked += 1
                return
        checked += 1
        if resp.status_code == e_code and e_string in resp.text:
            found.append({"name": name, "url": url})

    async with httpx.AsyncClient(follow_redirects=True) as client:
        await asyncio.gather(*(_check_one(s, client) for s in sites))

    return {"ok": True, "found": found, "checked": checked, "total_sites": len(sites)}


async def _run_holehe_subprocess(email: str, cwd: str, timeout: float = 60.0) -> None:
    """Esegue il binario holehe (subprocess async, non bloccante) nella cwd
    data, dove scriverà un file holehe_{timestamp}_{email}_results.csv.
    Isolata in una funzione a parte così i test la monkeypatchano invece di
    invocare il vero binario (che spammerebbe ~120 siti reali). Solleva
    asyncio.TimeoutError se supera il timeout (killando il processo prima di
    rilanciare), o le eccezioni native del subprocess (es. FileNotFoundError
    se holehe non è installato) — il chiamante le traduce in {"ok": False}."""
    exe = str(Path(sys.executable).parent / "holehe")
    proc = await asyncio.create_subprocess_exec(
        exe, email, "--only-used", "--no-color", "-C",
        cwd=cwd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise


async def holehe_lookup(email: str) -> dict:
    """Holehe (subprocess): su quali servizi è registrata un'email, via i
    loro flussi di recupero password — NON è un vero invio di recovery, si
    ferma al passo che rivela solo se l'account esiste, ma interroga comunque
    ~120 servizi terzi con l'indirizzo. ON-DEMAND (non auto-run: 30-60s per
    ~120 siti). {"ok": True, "found": [{"site": str, "domain": str}],
    "checked": int} oppure {"ok": False, "error": str}. --only-used filtra
    solo la stampa a console di holehe, non il CSV: il filtro exists==True è
    fatto qui in fase di parsing."""
    with tempfile.TemporaryDirectory(prefix="poe-holehe-") as tmpdir:
        try:
            await _run_holehe_subprocess(email, tmpdir)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Holehe: timeout (troppi siti da controllare, riprova)"}
        except FileNotFoundError:
            return {"ok": False, "error": "Holehe non installato (uv add holehe)"}
        except Exception:
            return {"ok": False, "error": "Holehe: errore di esecuzione"}

        csv_files = list(Path(tmpdir).glob("holehe_*_results.csv"))
        if not csv_files:
            return {"ok": False, "error": "Holehe: nessun output prodotto"}
        with csv_files[0].open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

    found = [
        {"site": row.get("name", "?"), "domain": row.get("domain")}
        for row in rows
        if str(row.get("exists", "")).strip().lower() == "true"
    ]
    return {"ok": True, "found": found, "checked": len(rows)}


async def test_ipqs_key(api_key: str) -> dict:
    """Sonda l'endpoint email con un indirizzo di prova — IPQualityScore non
    ha un endpoint dedicato "solo verifica chiave": la verifica consuma 1
    query minima (stesso principio di test_abuseipdb_key/test_virustotal_key).
    {"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://ipqualityscore.com/api/json/email/{quote(api_key, safe='')}/test@example.com")
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}
    data = resp.json()
    if data.get("success"):
        return {"ok": True, "detail": "chiave valida"}
    return {"ok": False, "error": "chiave non valida"}


async def test_numverify_key(api_key: str) -> dict:
    """Sonda l'endpoint validate con un numero di prova — Numverify non ha un
    endpoint dedicato "solo verifica chiave": la verifica consuma 1 query
    minima. {"ok": True, "detail": str} oppure {"ok": False, "error": str}."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://apilayer.net/api/validate",
                                    params={"access_key": api_key, "number": "14158586273"})
    except Exception:
        return {"ok": False, "error": "errore di rete o timeout"}
    # Gli errori Numverify arrivano con status HTTP veri: leggere il corpo prima
    # di guardare lo status, altrimenti "chiave sbagliata" e "quota finita"
    # diventano lo stesso identico "risposta inattesa".
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}
    if isinstance(data, dict) and data.get("success") is False:
        return {"ok": False, "error": _numverify_error(data).removeprefix("Numverify: ")}
    if resp.status_code != 200:
        return {"ok": False, "error": f"risposta inattesa ({resp.status_code})"}
    return {"ok": True, "detail": "chiave valida"}
