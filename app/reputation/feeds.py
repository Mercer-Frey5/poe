"""feeds.py — parser dei feed reputation (abuse.ch + blocklist.de) → righe
normalizzate {value,type,threat,reference}."""
from __future__ import annotations

import csv
import ipaddress
import json
from pathlib import Path

import httpx
import yaml

# Mappa ioc_type ThreatFox → tipo entità POE
_TF_TYPE = {
    "ip:port": "ipv4", "ipv4": "ipv4",
    "domain": "domain", "url": "url",
    "sha256_hash": "hash_sha256", "md5_hash": "hash_md5",
}


def _norm(value: str, etype: str) -> str:
    """Normalizza come li memorizza POE: domini/hash lowercase, IP senza porta."""
    v = value.strip()
    if etype == "ipv4":
        v = v.split(":", 1)[0]           # strip :port
    if etype in ("domain", "hash_sha256", "hash_md5"):
        v = v.lower()
    return v


def parse_threatfox_json(raw: str) -> list[dict]:
    data = json.loads(raw)
    out: list[dict] = []
    # export/json/recent: mapping id → [ {ioc_value, ioc_type, malware, reference} ]
    entries = data.values() if isinstance(data, dict) else data
    for group in entries:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            val = item.get("ioc_value")
            if not isinstance(val, str) or not val:
                continue
            etype = _TF_TYPE.get(item.get("ioc_type"))
            if not etype:
                continue
            out.append({
                "value": _norm(val, etype), "type": etype,
                "threat": item.get("malware"), "reference": item.get("reference"),
            })
    return out


def parse_urlhaus_csv(raw: str) -> list[dict]:
    out: list[dict] = []
    lines = [ln for ln in raw.splitlines() if ln and not ln.startswith("#")]
    for row in csv.reader(lines):
        # id,dateadded,url,url_status,last_online,threat,tags,urlhaus_link,reporter
        if len(row) < 8:
            continue
        out.append({
            "value": row[2].strip(), "type": "url",
            "threat": row[5].strip() or None, "reference": row[7].strip() or None,
        })
    return out


def parse_feodo_json(raw: str) -> list[dict]:
    data = json.loads(raw)
    out: list[dict] = []
    for item in data if isinstance(data, list) else []:
        ip = item.get("ip_address")
        if not ip:
            continue
        out.append({
            "value": ip.strip(), "type": "ipv4",
            "threat": item.get("malware"),
            "reference": "https://feodotracker.abuse.ch/browse/",
        })
    return out


def parse_mb_txt(raw: str) -> list[dict]:
    out: list[dict] = []
    for ln in raw.splitlines():
        ln = ln.strip().strip('"')
        if not ln or ln.startswith("#"):
            continue
        h = ln.lower()
        out.append({
            "value": h, "type": "hash_sha256", "threat": None,
            "reference": f"https://bazaar.abuse.ch/sample/{h}/",
        })
    return out


def parse_blocklistde_txt(raw: str) -> list[dict]:
    """Lista aggregata di blocklist.de (un IP per riga, IPv4+IPv6 miste).
    Nessun campo threat/reference nel feed: costruisce un reference verso la
    pagina di ricerca pubblica. IPv6 fuori scope POE, scartate."""
    out: list[dict] = []
    for ln in raw.splitlines():
        v = ln.strip()
        if not v:
            continue
        try:
            ipaddress.ip_address(v)
        except ValueError:
            continue
        if ":" in v:
            continue
        out.append({
            "value": v, "type": "ipv4", "threat": None,
            "reference": f"https://www.blocklist.de/en/search.html?ip={v}",
        })
    return out


FORMAT_PARSERS = {
    "threatfox_json": parse_threatfox_json,
    "urlhaus_csv": parse_urlhaus_csv,
    "feodo_json": parse_feodo_json,
    "mb_txt": parse_mb_txt,
    "blocklistde_txt": parse_blocklistde_txt,
}


_FEEDS_YAML = Path(__file__).resolve().parent.parent / "config" / "reputation_feeds.yaml"


def load_feeds() -> list[dict]:
    with open(_FEEDS_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


async def download_feed(url: str) -> str:
    """Scarica un feed (recente/bounded → text ok). Timeout ampio, segue redirect."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
