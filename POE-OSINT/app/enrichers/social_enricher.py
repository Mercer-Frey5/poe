"""Social handle platform disambiguation — regex on context, zero HTTP."""
from __future__ import annotations

import re

__all__ = ["disambiguate_platform"]

_PLATFORM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("linkedin",  re.compile(r"linkedin\.com", re.IGNORECASE)),
    ("twitter",   re.compile(r"(?:twitter|x)\.com", re.IGNORECASE)),
    ("instagram", re.compile(r"instagram\.com", re.IGNORECASE)),
    ("telegram",  re.compile(r"(?:t\.me|telegram\.(?:me|org))", re.IGNORECASE)),
    ("github",    re.compile(r"github\.com", re.IGNORECASE)),
    ("facebook",  re.compile(r"(?:facebook|fb)\.com", re.IGNORECASE)),
    ("tiktok",    re.compile(r"tiktok\.com", re.IGNORECASE)),
]


def disambiguate_platform(handle: str, context: str) -> str:
    """Return platform name or 'unknown' based on URL clues in surrounding text."""
    for platform, pattern in _PLATFORM_PATTERNS:
        if pattern.search(context):
            return platform
    return "unknown"
