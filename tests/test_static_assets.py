"""Asset statici e coerenza fra template e CSS.

Copre due classi di bug gia' viste in produzione:

1. **`display:flex` che sovrascrive `[hidden]`** — l'attributo HTML `hidden`
   vale `display:none` solo come regola dello user-agent: qualsiasi
   `display:flex` in un foglio d'autore la batte. Un elemento nascosto di
   default resta quindi visibile come box vuoto. E' successo su
   `.status-item`, `.status-others-list`, `.poe-ai-picker` e `.poe-ai-models`:
   quattro volte lo stesso errore, quindi qui c'e' un guard generico.

2. **Cache-bust disallineato** — `style.css` e `app.js` cambiano insieme; se
   solo uno ha il `?v=` aggiornato il browser serve meta' vecchio e meta'
   nuovo, con sintomi incomprensibili.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STYLE = _ROOT / "static" / "style.css"
_APPJS = _ROOT / "static" / "app.js"
_BASE = _ROOT / "app" / "templates" / "base.html"
_TEMPLATES = _ROOT / "app" / "templates"

_DISPLAY_OVERRIDES = ("flex", "grid", "inline-flex", "inline-grid", "block", "inline-block")


def _css() -> str:
    return _STYLE.read_text(encoding="utf-8")


def _hidden_toggled_classes() -> set[str]:
    """Classi di elementi che vengono mostrati/nascosti con l'attributo `hidden`,
    raccolte sia dai template (attributo `hidden` in un tag) sia da app.js
    (`el.hidden = ...`). Per app.js si risale alla classe via il selettore
    querySelector piu' vicino, quindi si tiene una lista esplicita: i nomi sono
    pochi e cambiano di rado, ed e' preferibile un elenco leggibile a un parser
    JS fragile."""
    found: set[str] = set()

    # Template: <div class="a b" ... hidden> — `hidden` senza valore, non aria-hidden.
    tag_re = re.compile(r"<[^>]*\bclass=\"([^\"]+)\"[^>]*>", re.S)
    for tpl in _TEMPLATES.glob("*.html"):
        for tag in tag_re.finditer(tpl.read_text(encoding="utf-8")):
            whole = tag.group(0)
            # `hidden` come attributo a se': preceduto da spazio, non da `-`
            # (escluderebbe `aria-hidden` e le classi BEM `--hidden`) e non
            # seguito da `=`.
            if re.search(r"(?<![-\w])hidden(?![-\w=])", whole):
                found.update(tag.group(1).split())

    # app.js: elementi toggolati via `.hidden =`, con la classe nota dal CSS.
    js = _APPJS.read_text(encoding="utf-8")
    for cls in ("poe-ai-models", "poe-ai-picker", "status-others", "status-others-list"):
        if cls in js:
            found.add(cls)
    return found


@pytest.mark.parametrize("cls", sorted(_hidden_toggled_classes()))
def test_hidden_non_sovrascritto_da_display(cls: str):
    """Se una classe toggolata via `hidden` ha un `display` d'autore, deve
    esistere anche la regola `.classe[hidden] { display: none }`."""
    css = _css()
    rule_re = re.compile(
        r"\.%s\s*(?:[,{][^{}]*)?\{([^{}]*)\}" % re.escape(cls), re.S
    )
    sets_display = any(
        re.search(r"display\s*:\s*(%s)\b" % "|".join(_DISPLAY_OVERRIDES), body)
        for body in rule_re.findall(css)
    )
    if not sets_display:
        pytest.skip(f".{cls} non imposta un display che possa battere [hidden]")
    assert re.search(r"\.%s\[hidden\]\s*\{[^}]*display\s*:\s*none" % re.escape(cls), css), (
        f".{cls} imposta display:{_DISPLAY_OVERRIDES} ma non ha l'override "
        f".{cls}[hidden] {{ display: none }} — l'elemento resterebbe visibile "
        f"anche con l'attributo hidden."
    )


def test_favicon_dichiarata_e_presente():
    """Senza <link rel=icon> il browser sonda /favicon.ico e
    /apple-touch-icon*.png -> 404 ripetuti nei log."""
    base = _BASE.read_text(encoding="utf-8")
    assert 'rel="icon"' in base, "manca <link rel=icon> in base.html"
    assert 'rel="apple-touch-icon"' in base, "manca <link rel=apple-touch-icon>"

    for m in re.finditer(r'rel="(?:icon|apple-touch-icon)"[^>]*href="/static/([^"?]+)', base):
        asset = _ROOT / "static" / m.group(1)
        assert asset.is_file(), f"favicon punta a {m.group(1)} che non esiste in static/"


def test_cache_bust_style_e_appjs_allineati():
    """style.css e app.js si evolvono insieme: versioni diverse servono al
    browser un mix di vecchio e nuovo."""
    base = _BASE.read_text(encoding="utf-8")
    style_v = re.search(r'style\.css\?v=([0-9.]+)', base)
    app_v = re.search(r'app\.js\?v=([0-9.]+)', base)
    assert style_v and app_v, "cache-bust ?v= assente su style.css o app.js"
    assert style_v.group(1) == app_v.group(1), (
        f"cache-bust disallineato: style.css={style_v.group(1)} app.js={app_v.group(1)}"
    )
