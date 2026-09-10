"""ip_info.py — info locali (nessuna rete) su IP privati/bogon: range RFC, CIDR/netmask.
Per IP pubblici ritorna None (per quelli si usa il catalogo OSINT esterno, non questo)."""
from __future__ import annotations

import ipaddress


def private_ip_info(value: str) -> dict | None:
    """None se l'IP non è privato/bogon o non è parsabile."""
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if addr.is_global:
        return None

    if addr.is_loopback:
        range_name = "Loopback (localhost)"
    elif addr.is_link_local:
        range_name = "Link-local (APIPA/auto-configurazione)"
    elif addr.is_private:
        range_name = "Rete privata (RFC 1918)"
    else:
        range_name = "Non instradabile (bogon)"

    octets = str(addr).split(".")
    if octets[0].isdigit() and int(octets[0]) < 128:
        legacy_class = "A"
    elif octets[0].isdigit() and int(octets[0]) < 192:
        legacy_class = "B"
    elif octets[0].isdigit() and int(octets[0]) < 224:
        legacy_class = "C"
    else:
        legacy_class = None

    return {
        "range_name": range_name,
        "legacy_class": legacy_class,
        "is_private": bool(addr.is_private),
    }
