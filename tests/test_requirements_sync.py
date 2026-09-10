"""pyproject.toml, requirements.txt e gli import reali di app/ devono coincidere.

`requirements.txt` era rimasto fermo a v0.3 mentre `app/` aveva iniziato a
importare dotenv, httpx, ollama, reportlab, whois e markdown_it. Siccome il
Dockerfile installa da requirements.txt (non da pyproject.toml), l'immagine
Docker non si avviava piu': il difetto era invisibile in locale, dove si usa
`uv` e quindi pyproject.

Stesso discorso per la versione: `pyproject.toml` diceva 0.6.0 e la FastAPI app
pure, mentre la UI era gia' a 0.7.x."""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_REQUIREMENTS = _ROOT / "requirements.txt"

# Distribuzione PyPI -> nome del modulo importato, quando differiscono.
_DIST_TO_MODULE = {
    "python-dotenv": "dotenv",
    "python-whois": "whois",
    "pyyaml": "yaml",
    "markdown-it-py": "markdown_it",
    "python-multipart": "multipart",
    "mlx-lm": "mlx_lm",
    "uvicorn[standard]": "uvicorn",
}

# Moduli importati da app/ che NON vanno dichiarati: arrivano garantiti con
# un'altra dipendenza diretta.
_FORNITI_DA_ALTRI = {
    "starlette",  # dipendenza core di fastapi
}


def _stdlib() -> set[str]:
    return set(sys.stdlib_module_names)


def _deps_pyproject() -> dict[str, str]:
    """Nome distribuzione (normalizzato) -> riga originale."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    out = {}
    for raw in data["project"]["dependencies"]:
        name = re.split(r"[<>=!;\s]", raw, maxsplit=1)[0].strip()
        out[name.lower()] = raw
    return out


def _deps_requirements() -> set[str]:
    out = set()
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        out.add(re.split(r"[<>=!;\s]", line, maxsplit=1)[0].strip().lower())
    return out


def _moduli_importati_da_app() -> set[str]:
    """Moduli top-level importati da app/, esclusi stdlib e i moduli interni."""
    found: set[str] = set()
    for py in (_ROOT / "app").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
    return found - _stdlib() - {"app"} - _FORNITI_DA_ALTRI


def _moduli_dichiarati() -> set[str]:
    mods = set()
    for dist in _deps_pyproject():
        mods.add(_DIST_TO_MODULE.get(dist, dist.replace("-", "_")))
    return mods


def test_ogni_import_di_app_e_dichiarato():
    mancanti = sorted(_moduli_importati_da_app() - _moduli_dichiarati())
    assert not mancanti, (
        "app/ importa moduli non dichiarati in pyproject.toml: "
        + ", ".join(mancanti)
    )


def test_requirements_copre_le_dipendenze_runtime():
    """requirements.txt alimenta il Dockerfile: deve contenere ogni dipendenza
    di pyproject che serve davvero in container. Sono ammesse assenze solo per
    le dipendenze con marker di piattaforma (mlx-lm, solo macOS) e per `mcp`,
    che serve al connettore poe_mcp/ non copiato nell'immagine."""
    # Le dipendenze con marker di piattaforma non riguardano l'immagine Linux;
    # `mcp` serve solo al connettore poe_mcp/, che non viene copiato dentro.
    solo_altra_piattaforma = {
        name for name, raw in _deps_pyproject().items() if "sys_platform" in raw
    }
    attese = set(_deps_pyproject()) - solo_altra_piattaforma - {"mcp"}
    mancanti = sorted(attese - _deps_requirements())
    assert not mancanti, (
        "dipendenze in pyproject.toml assenti da requirements.txt "
        f"(immagine Docker non avviabile): {', '.join(mancanti)}"
    )


def test_requirements_non_dichiara_pacchetti_sconosciuti():
    """L'inverso: niente pacchetti in requirements.txt che pyproject non conosce
    (a parte i tool di test)."""
    tool_di_test = {"pytest"}
    extra = sorted(_deps_requirements() - set(_deps_pyproject()) - tool_di_test)
    assert not extra, (
        "requirements.txt dichiara pacchetti assenti da pyproject.toml: "
        + ", ".join(extra)
    )


def test_versione_unica_fra_pyproject_e_runtime():
    from app import __version__

    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__, (
        f"pyproject.toml dice {data['project']['version']}, "
        f"app.__version__ dice {__version__}"
    )


def test_dockerfile_label_allineata():
    """La LABEL OCI era rimasta a 0.1.0: un'immagine che si dichiara v0.1
    rende impossibile capire cosa gira in produzione."""
    from app import __version__

    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    m = re.search(r'org\.opencontainers\.image\.version="([^"]+)"', dockerfile)
    assert m, "Dockerfile senza LABEL org.opencontainers.image.version"
    assert m.group(1) == __version__, (
        f"Dockerfile dichiara {m.group(1)}, app.__version__ dice {__version__}"
    )


def test_app_fastapi_espone_la_versione_corrente():
    from app import __version__
    from app.main import app

    assert app.version == __version__


def test_dockerfile_non_esegue_come_root():
    """POE tratta dati altrui (OSINT, PII): un processo che gira come root nel
    container non ne ha bisogno, e chi scarica il progetto non deve doverlo
    scoprire da solo leggendo il Dockerfile riga per riga."""
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER\s+\S+", dockerfile, re.M), \
        "Dockerfile non imposta un utente non-root (USER)"
