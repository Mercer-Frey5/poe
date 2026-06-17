"""
refresh_tlds.py — aggiorna app/config/tld_list.yaml dalla sorgente IANA.

Uso:
    python scripts/refresh_tlds.py

Scarica la lista canonica da
https://data.iana.org/TLD/tlds-alpha-by-domain.txt, valida il
contenuto, riscrive il file YAML. È pensato per essere eseguito
manualmente dall'Operatore ogni 6-12 mesi.

NON viene chiamato a build/install: POE non fa mai chiamate di rete
in fase di setup. Questo script è un tool di manutenzione esplicita.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml


IANA_URL = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
USER_AGENT = "POE-Refresh-TLDs/0.3 (+https://github.com)"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "config" / "tld_list.yaml"


def fetch_iana_tlds() -> tuple[list[str], str]:
    """
    Scarica e parsa la lista IANA. Ritorna (lista_tld_lowercase, timestamp_header).

    La prima riga del file IANA è un commento del tipo
        # Version 2024010800, Last Updated Mon Jan  8 07:07:01 2024 UTC
    Lo conserviamo come metadato.
    """
    try:
        req = Request(IANA_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            content = resp.read().decode("ascii", errors="strict")
    except URLError as e:
        raise SystemExit(f"errore di rete: {e}")

    lines = content.strip().splitlines()
    if not lines:
        raise SystemExit("risposta IANA vuota")

    header = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else "no header"
    body = lines[1:] if lines[0].startswith("#") else lines

    tlds = [line.strip().lower() for line in body if line.strip()]

    # Validazione: TLD ASCII alfanumerica, almeno 2 caratteri
    for tld in tlds:
        if not tld.isalnum() or len(tld) < 2:
            raise SystemExit(f"TLD malformata: {tld!r}")

    if len(tlds) < 1000:
        raise SystemExit(f"troppe poche TLD ({len(tlds)}), risposta probabilmente corrotta")

    return tlds, header


def write_yaml(tlds: list[str], iana_header: str) -> None:
    """Scrive il YAML con metadata di tracciabilità in testa."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    metadata_comment = (
        f"# IANA TLD list — aggiornata via scripts/refresh_tlds.py\n"
        f"# Sorgente: {IANA_URL}\n"
        f"# Header IANA: {iana_header}\n"
        f"# Refresh effettuato: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"# Conteggio: {len(tlds)} TLD\n"
        f"#\n"
        f"# NON modificare a mano. Per aggiornare:\n"
        f"#     python scripts/refresh_tlds.py\n"
        f"\n"
    )

    yaml_body = yaml.safe_dump(
        sorted(tlds),
        default_flow_style=False,
        allow_unicode=False,
    )

    OUTPUT_PATH.write_text(metadata_comment + yaml_body, encoding="utf-8")


def main() -> None:
    print(f"Scarico lista TLD da {IANA_URL}...")
    tlds, header = fetch_iana_tlds()
    print(f"  ricevute {len(tlds)} TLD ({header})")

    write_yaml(tlds, header)
    print(f"  scritte in {OUTPUT_PATH.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
