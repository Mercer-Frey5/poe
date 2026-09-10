"""Regression: nessun handler onclick inline nei template.

La CSP del progetto usa `script-src 'self'` (senza 'unsafe-inline'): gli
`onclick="..."` inline vengono BLOCCATI dal browser → l'espansione delle card
e gli altri handler smetterebbero di funzionare. Tutto deve passare per
event-delegation in static/app.js.
"""
import pathlib


def test_no_inline_onclick_in_templates():
    tdir = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
    offenders = [p.name for p in tdir.glob("*.html") if "onclick=" in p.read_text(encoding="utf-8")]
    assert not offenders, f"onclick inline (bloccato da CSP) trovato in: {offenders}"


def test_htmx_served_locally_not_from_cdn():
    """htmx deve essere servito in locale (static/htmx.min.js), non da CDN.
    POE è offline/local-first: una CDN lenta/bloccata lasciava window.htmx
    undefined e i lookup live bloccati per sempre su 'Verifica in corso'."""
    root = pathlib.Path(__file__).resolve().parent.parent
    base = (root / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "unpkg" not in base, "htmx non deve venire da unpkg (CDN): servilo in locale"
    assert "/static/htmx.min.js" in base, "base.html deve caricare htmx da /static/"
    assert (root / "static" / "htmx.min.js").exists(), "manca static/htmx.min.js in locale"


def test_csp_has_no_external_script_source():
    """La CSP script-src non deve più includere CDN esterne (htmx è locale)."""
    main_py = (pathlib.Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert "unpkg" not in main_py, "rimuovi unpkg dalla CSP: htmx è servito in locale"
