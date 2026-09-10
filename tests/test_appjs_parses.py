"""Regression: static/app.js deve essere JS valido (no parse error).

Un errore di sintassi in app.js renderebbe `toggleCard` (e tutto il resto)
undefined → l'espansione delle card IOC smetterebbe di funzionare.
"""
import pathlib
import shutil
import subprocess

import pytest


def test_appjs_node_check():
    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")
    r = subprocess.run([node, "--check", "static/app.js"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _estrai_funzione(nome: str, sorgente: str) -> str:
    import re
    m = re.search(rf"^\s*function {re.escape(nome)}\(.*?\n    \}}", sorgente, re.S | re.M)
    assert m, f"funzione {nome} non trovata in app.js"
    return m.group(0)


def test_picker_status_bar_non_mostra_locale_per_un_backend_cloud():
    """Il picker 'Motore LLM' nella status bar offre solo mlx/claude, ma deve
    MOSTRARE correttamente uno stato impostato altrove (pannello Settings): un
    backend compatibile OpenAI puntato a un endpoint pubblico e' kind='cloud',
    e prima veniva etichettato '· Llama' come se fosse il modello locale —
    l'esatto contrario di quel che stava succedendo ai dati analizzati."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")

    sorgente = pathlib.Path("static/app.js").read_text(encoding="utf-8")
    current_label = _estrai_funzione("currentLabel", sorgente)

    # currentLabel() non prende argomenti: legge `state` dalla closure esterna,
    # come nel file vero. Qui si simula la stessa closure per ogni caso.
    script = f"""
function mapKind(kind) {{
    return kind === 'claude' ? 'claude' : (kind === 'cloud' ? 'cloud' : 'local');
}}
function label(kind, model) {{
    var state = {{ backend: mapKind(kind), model: model || '' }};
{current_label}
    return currentLabel();
}}
console.log(JSON.stringify({{
    local:  label('local'),
    cloud:  label('cloud'),
    claude: label('claude', 'sonnet'),
}}));
"""
    r = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout)
    assert out["local"] == "· Llama"
    assert out["claude"] == "· Claude Sonnet"
    assert out["cloud"] != "· Llama", "un endpoint cloud non deve apparire come locale"
