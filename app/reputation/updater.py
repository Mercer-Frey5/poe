"""updater.py — refresh dei feed reputation (background-safe, downloader iniettabile)."""
from __future__ import annotations

import logging

from app.reputation import feeds as _feeds
from app.reputation import store

logger = logging.getLogger(__name__)


async def refresh_stale(force: bool = False, downloader=None) -> dict[str, str]:
    """Per ogni feed stale (o tutti se force), scarica→parsa→salva. Non solleva:
    ritorna {nome: 'updated:N' | 'fresh' | 'error'}. `downloader` iniettabile per i test."""
    dl = downloader or _feeds.download_feed
    results: dict[str, str] = {}
    for feed in _feeds.load_feeds():
        name = feed["name"]
        if not force and not store.is_stale(name, feed["ttl_hours"]):
            results[name] = "fresh"
            continue
        try:
            raw = await dl(feed["url"])
            parser = _feeds.FORMAT_PARSERS[feed["format"]]
            rows = parser(raw)
            store.replace_source(name, rows)
            results[name] = f"updated:{len(rows)}"
        except Exception:
            logger.exception("reputation feed %s refresh failed", name)
            results[name] = "error"
    return results
