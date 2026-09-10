"""build_pdf_report — export PDF ben formattato (AI): stessa fonte dati raw
di report.py (enrichment + tool live + analisi AI), leggibile invece di JSON
grezzo. Verifica strutturale (magic bytes) + contenuto reale via estrazione
testo (pypdf, dev-only)."""
from io import BytesIO

from pypdf import PdfReader

from app.pdf_report import build_pdf_report, markdown_to_flowables, _pdf_styles


def _obs(entities=None, label=None):
    return {
        "id": 7, "timestamp": "2026-07-12T10:00:00", "raw_input": "test input",
        "entities": entities or [], "kept": False, "label": label,
    }


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_pdf_starts_with_valid_magic_bytes():
    pdf_bytes = build_pdf_report(_obs())
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_contains_title_and_entity_value():
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium", "metadata": {}}]
    pdf_bytes = build_pdf_report(_obs(entities=entities, label="Osservazione #7"))
    text = _extract_text(pdf_bytes)
    assert "Osservazione #7" in text
    assert "132.144.1.4" in text


def test_pdf_enrichment_rendered_readable_not_raw_json():
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium",
                 "metadata": {"isp": "DoD Network Information Center", "country": "United States"}}]
    pdf_bytes = build_pdf_report(_obs(entities=entities))
    text = _extract_text(pdf_bytes)
    assert "DoD Network Information Center" in text
    assert '{"isp"' not in text  # non JSON grezzo, leggibile


def test_pdf_includes_live_lookup_data_labeled_by_source():
    entities = [{"type": "ipv4", "value": "132.144.1.4", "original": "132.144.1.4",
                 "confidence": "medium", "metadata": {}}]
    live_results_by_value = {
        "132.144.1.4": {"AbuseIPDB": {"ok": True, "abuse_score": 0, "usage_type": "Government"}},
    }
    pdf_bytes = build_pdf_report(_obs(entities=entities), live_results_by_value=live_results_by_value)
    text = _extract_text(pdf_bytes)
    assert "AbuseIPDB" in text
    assert "Government" in text


def test_pdf_includes_ai_analysis_section_when_provided():
    pdf_bytes = build_pdf_report(_obs(), analysis_text="Analisi generata di test.", analysis_model="fake-model")
    text = _extract_text(pdf_bytes)
    assert "Analisi generata di test." in text
    assert "fake-model" in text


def test_pdf_graceful_note_when_analysis_missing():
    pdf_bytes = build_pdf_report(_obs(), analysis_text=None)
    text = _extract_text(pdf_bytes)
    assert "non disponibil" in text.lower()


def test_pdf_includes_synthesis_when_present():
    obs = _obs()
    obs["synthesis_text"] = "Sintesi salvata di test."
    obs["synthesis_model"] = "modelX"
    pdf_bytes = build_pdf_report(obs)
    text = _extract_text(pdf_bytes)
    assert "Sintesi salvata di test." in text


# ── markdown_to_flowables: l'analisi LLM è markdown, non deve finire grezza
# nel PDF (bug reale: "**Sintesi esecutiva**" con asterischi letterali). ──

def _md_pdf(md: str) -> str:
    """Rende un markdown dentro un PDF minimale ed estrae il testo, per
    verificare che il converter produca flowable validi renderizzabili."""
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import A4
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    doc.build(markdown_to_flowables(md, _pdf_styles()))
    return _extract_text(buf.getvalue())


def test_markdown_bold_not_rendered_literally():
    text = _md_pdf("Questo è **grassetto** nel testo.")
    assert "grassetto" in text
    assert "**" not in text  # gli asterischi markdown NON compaiono


def test_markdown_headings_and_bullets():
    text = _md_pdf("## Verdetto\n\n- primo punto\n- secondo punto")
    assert "Verdetto" in text
    assert "##" not in text
    assert "primo punto" in text
    assert "secondo punto" in text


def test_markdown_ordered_list():
    text = _md_pdf("1. Uno\n2. Due\n3. Tre")
    assert "Uno" in text and "Due" in text and "Tre" in text


def test_markdown_escapes_angle_brackets_and_ampersand_no_crash():
    """Gotcha reportlab: un < seguito da lettera o una & nuda sollevano
    ValueError se non escapati. L'analisi LLM può contenere "porta 22 < 1024",
    "<script>", "R&D". Deve renderizzare il testo letterale, non crashare."""
    text = _md_pdf("La **porta 22 < 1024** è privilegiata; vedi <script> e R&D.")
    assert "porta 22" in text
    assert "1024" in text
    assert "R&D" in text or "R&amp;D" not in text  # niente escape visibile


def test_markdown_inline_code():
    text = _md_pdf("Usa il campo `abuse_score` del report.")
    assert "abuse_score" in text
