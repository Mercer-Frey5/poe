"""pdf_report.py — export PDF investigativo ben formattato (variante "AI" dello
Scarica): stessa fonte di dati raw usata dal .md e dal prompt LLM (enrichment
completo + risultati dei tool live già interrogati, vedi report.py e
_observation_report_context in app/main.py), ma con identità visiva POE
(brand header/footer, badge severità, tabelle enrichment) e l'analisi
investigativa LLM resa da markdown a testo formattato.

Libreria: reportlab (pura Python, nessuna dipendenza nativa — fit M1/locale,
vedi CLAUDE.md). WeasyPrint (Pango nativo) e borb (AGPL) scartati apposta.
L'analisi LLM è markdown: convertita in flowable con markdown-it-py (pure
Python) invece di finire grezza con gli asterischi a vista."""
from __future__ import annotations

import re
from io import BytesIO
from xml.sax.saxutils import escape

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable, ListFlowable, ListItem, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.scoring import compute_accuracy, compute_score, group_by_type

# ── Identità visiva POE ("terminale ambra", vedi docs/ui-guidelines.md) ──
# Token esatti della UI: bruno scuro caldo + ambra, mono ovunque. La banda
# header/i titoli portano l'identità dark+ambra; il corpo resta chiaro per
# la leggibilità in stampa, con inchiostro caldo (non nero freddo).
POE_ORANGE = colors.HexColor("#fa8c16")     # accento ambra POE
POE_AMBER_DK = colors.HexColor("#d97706")   # ambra scuro
POE_INK = colors.HexColor("#1a1814")        # sfondo bruno scuro caldo POE
POE_INK_SOFT = colors.HexColor("#2c281f")   # elevated
POE_BODY = colors.HexColor("#2a2620")       # testo corpo (near-black caldo, leggibile)
POE_SLATE = colors.HexColor("#746551")      # muto caldo (secondario su bianco)
POE_ZEBRA = colors.HexColor("#f7f3ea")      # off-white caldo (righe alterne)
POE_HAIR = colors.HexColor("#e6ddcb")       # bordo caldo chiaro
POE_CREAM = colors.HexColor("#fffdf7")      # testo su banda scura

# Severità: colore SEMPRE accompagnato da label testuale (accessibilità).
# Tonalità POE (danger/warning/success), scurite dove serve contrasto col label.
_SEVERITY = {
    "critico": (colors.HexColor("#c2543d"), "CRITICO"),
    "sospetto": (colors.HexColor("#c98a1e"), "SOSPETTO"),
    "basso": (colors.HexColor("#6f8a54"), "BASSO"),
    None: (POE_SLATE, "INFORMATIVO"),
}

# Font: built-in reportlab. POE è tutto IBM Plex Mono ("terminale ambra"):
# Courier è lo stand-in monospace per brand/titoli/dati/IOC; il corpo resta
# proporzionale (Helvetica) perché il testo giustificato in monospace crea
# buchi. Bundle di IBM Plex Mono OFL possibile in futuro per fedeltà piena.
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_MONO = "Courier"
_FONT_MONO_BOLD = "Courier-Bold"

_MARGIN = 1.8 * cm
_CONTENT_WIDTH = A4[0] - 2 * _MARGIN

# Chiavi puramente di servizio, mai utili a un lettore umano.
_SKIP_KEYS = {"ok", "extractor", "type_hint"}
# Acronimi comuni nei dati OSINT: restano maiuscoli invece di "Title Case".
_ACRONYMS = {"isp", "asn", "cve", "ip", "os", "cidr", "rdap", "as", "tor", "org", "url", "dns", "cpe", "bgp"}


def _humanize_key(key: str) -> str:
    """snake_case/camelCase -> "Label leggibile", con acronimi noti maiuscoli."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key)
    words = [w for w in snake.replace("_", " ").split(" ") if w]
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w.capitalize() for w in words)


def _stringify(v) -> str:
    if isinstance(v, bool):
        return "sì" if v else "no"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def _format_raw_dict(d: dict) -> list[tuple[str, str]]:
    """dict raw (metadata o risultato tool) -> coppie (Label, valore) leggibili,
    saltando chiavi di servizio e valori vuoti."""
    out = []
    for k, v in d.items():
        if k in _SKIP_KEYS or v in (None, "", []):
            continue
        out.append((_humanize_key(k), _stringify(v)))
    return out


# ── Stili ───────────────────────────────────────────────────────────────────

def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        # Titolo: mono (terminale POE), inchiostro scuro caldo.
        "title": ParagraphStyle("poe_title", parent=base["Title"], fontName=_FONT_MONO_BOLD,
                                 fontSize=17, leading=21, textColor=POE_INK, spaceAfter=2),
        "meta": ParagraphStyle("poe_meta", parent=base["BodyText"], fontName=_FONT_MONO,
                                fontSize=8, leading=12, textColor=POE_SLATE),
        # Titoli sezione: mono ambra, come i "▸ titolo" della UI POE.
        "h2": ParagraphStyle("poe_h2", parent=base["Heading2"], fontName=_FONT_MONO_BOLD,
                             fontSize=11.5, leading=15, textColor=POE_ORANGE,
                             spaceBefore=15, spaceAfter=5),
        "h3": ParagraphStyle("poe_h3", parent=base["Heading3"], fontName=_FONT_MONO_BOLD,
                             fontSize=9.8, leading=13, textColor=POE_INK, spaceBefore=9, spaceAfter=2),
        # Corpo: proporzionale GIUSTIFICATO (non più a sinistra), inchiostro caldo.
        "body": ParagraphStyle("poe_body", parent=base["BodyText"], fontName=_FONT,
                               fontSize=9.5, leading=14.5, textColor=POE_BODY,
                               spaceAfter=6, alignment=TA_JUSTIFY),
        "raw": ParagraphStyle("poe_raw", parent=base["BodyText"], fontName=_FONT_MONO,
                              fontSize=8, leading=11, textColor=POE_BODY),
        "kv_key": ParagraphStyle("poe_kv_key", parent=base["BodyText"], fontName=_FONT_MONO_BOLD,
                                 fontSize=8, leading=11, textColor=POE_SLATE),
        "kv_val": ParagraphStyle("poe_kv_val", parent=base["BodyText"], fontName=_FONT,
                                 fontSize=8.5, leading=11.5, textColor=POE_BODY),
        "mono_val": ParagraphStyle("poe_mono_val", parent=base["BodyText"], fontName=_FONT_MONO,
                                   fontSize=8.5, leading=11.5, textColor=POE_BODY),
        # Header di tabella: testo scuro su ambra (text-on-accent POE = #1a1814).
        "cell_head": ParagraphStyle("poe_cell_head", parent=base["BodyText"], fontName=_FONT_MONO_BOLD,
                                    fontSize=8, leading=11, textColor=POE_INK),
        # Stili heading per il converter markdown dell'analisi LLM (h1..h3):
        # mono, ambra scuro per distinguerli dai titoli-sezione arancioni.
        "md_h1": ParagraphStyle("poe_md_h1", parent=base["Heading2"], fontName=_FONT_MONO_BOLD,
                               fontSize=10.5, leading=14, textColor=POE_AMBER_DK, spaceBefore=9, spaceAfter=3),
        "md_h2": ParagraphStyle("poe_md_h2", parent=base["Heading3"], fontName=_FONT_MONO_BOLD,
                               fontSize=9.8, leading=13, textColor=POE_AMBER_DK, spaceBefore=8, spaceAfter=2),
        "md_h3": ParagraphStyle("poe_md_h3", parent=base["Heading4"], fontName=_FONT_MONO_BOLD,
                               fontSize=9.3, leading=12, textColor=POE_SLATE, spaceBefore=6, spaceAfter=2),
    }


# ── Markdown -> flowables (analisi LLM) ──────────────────────────────────────

_MD = MarkdownIt("commonmark")


def _inline_markup(node: SyntaxTreeNode) -> str:
    """Contenuto inline di un nodo -> mini-markup reportlab. Ogni foglia di
    testo è ESCAPATA (xml.sax.saxutils.escape gestisce & < > nell'ordine
    giusto) prima di iniettare i tag: un < seguito da lettera o una & nuda
    farebbero sollevare ValueError a reportlab."""
    parts: list[str] = []
    for child in node.children:
        t = child.type
        if t == "text":
            parts.append(escape(child.content))
        elif t == "inline":
            parts.append(_inline_markup(child))
        elif t == "strong":
            parts.append(f"<b>{_inline_markup(child)}</b>")
        elif t == "em":
            parts.append(f"<i>{_inline_markup(child)}</i>")
        elif t == "s":
            parts.append(f"<strike>{_inline_markup(child)}</strike>")
        elif t == "code_inline":
            parts.append(f'<font face="{_FONT_MONO}">{escape(child.content)}</font>')
        elif t == "link":
            href = escape(child.attrGet("href") or "")
            parts.append(f'<link href="{href}" color="#1A4C8B">{_inline_markup(child)}</link>')
        elif t == "softbreak":
            parts.append(" ")
        elif t == "hardbreak":
            parts.append("<br/>")
        elif child.children:
            parts.append(_inline_markup(child))
        elif child.content:
            parts.append(escape(child.content))
    return "".join(parts)


def _render_list(list_node: SyntaxTreeNode, styles: dict, bullet_type: str):
    items = []
    for li in list_node.children:  # list_item
        inner: list = []
        _render_blocks(li, styles, inner)
        if not inner:
            continue
        items.append(ListItem(inner if len(inner) > 1 else inner[0], leftIndent=6))
    return ListFlowable(items, bulletType=bullet_type, leftIndent=16, spaceBefore=2, spaceAfter=4)


def _render_blocks(parent: SyntaxTreeNode, styles: dict, out: list) -> None:
    for node in parent.children:
        t = node.type
        if t == "heading":
            level = min(int(node.tag[1]) if node.tag[1:].isdigit() else 3, 3)
            out.append(Paragraph(_inline_markup(node), styles[f"md_h{level}"]))
        elif t == "paragraph":
            out.append(Paragraph(_inline_markup(node), styles["body"]))
        elif t == "bullet_list":
            out.append(_render_list(node, styles, "bullet"))
        elif t == "ordered_list":
            out.append(_render_list(node, styles, "1"))
        elif t in ("fence", "code_block"):
            out.append(Preformatted(node.content.rstrip("\n"), styles["raw"]))
        elif t == "blockquote":
            _render_blocks(node, styles, out)
        elif t == "hr":
            out.append(HRFlowable(width="100%", color=POE_HAIR, spaceBefore=4, spaceAfter=4))
        elif node.children:
            _render_blocks(node, styles, out)


def markdown_to_flowables(text: str, styles: dict) -> list:
    """Converte l'analisi LLM (markdown) in flowable reportlab formattati —
    niente asterischi/cancelletti letterali nel PDF."""
    if not text or not text.strip():
        return []
    tree = SyntaxTreeNode(_MD.parse(text))
    out: list = []
    _render_blocks(tree, styles, out)
    return out


# ── Componenti tabellari ─────────────────────────────────────────────────────

def _kv_table(pairs: list[tuple[str, str]], styles: dict, header: str | None = None,
              header_color=POE_INK):
    """Tabella 2 colonne (Label | valore) zebra. header opzionale = riga
    intestazione colorata a tutta larghezza (nome fonte)."""
    rows = []
    style_cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, POE_HAIR),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    start = 0
    if header is not None:
        rows.append([Paragraph(escape(header), styles["cell_head"]), ""])
        style_cmds += [
            ("SPAN", (0, 0), (1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ]
        start = 1
    for i, (k, v) in enumerate(pairs):
        is_mono = bool(re.match(r"^[\d.:/ ,a-fx-]+$", v)) and any(ch.isdigit() for ch in v)
        rows.append([
            Paragraph(escape(k), styles["kv_key"]),
            Paragraph(escape(v), styles["mono_val"] if is_mono else styles["kv_val"]),
        ])
    for r in range(start, len(rows)):
        if (r - start) % 2 == 1:
            style_cmds.append(("BACKGROUND", (0, r), (-1, r), POE_ZEBRA))
    return Table(rows, colWidths=[4.6 * cm, _CONTENT_WIDTH - 4.6 * cm], style=TableStyle(style_cmds))


def _section(title: str, styles: dict):
    """Titolo di sezione con prefisso a chevron (convenzione UI POE "▸ titolo",
    reso con › — U+25B8 non è nell'encoding dei font base-14), mono ambra."""
    return Paragraph(f"&#8250; {escape(title)}", styles["h2"])


def _severity_badge(level, styles: dict):
    """Chip verdetto: cella colorata con label mono bianca centrata."""
    color, label = _SEVERITY.get(level, _SEVERITY[None])
    cell = Paragraph(f'<font face="{_FONT_MONO_BOLD}" color="white">{label}</font>', styles["h3"])
    return Table([[cell]], colWidths=[3.4 * cm], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))


def _key_scores(live: dict) -> str:
    """Riga compatta "punteggi chiave" per la tabella riepilogo, dai tool live."""
    bits = []
    ab = live.get("AbuseIPDB")
    if ab and ab.get("ok") and ab.get("abuse_score") is not None:
        bits.append(f"AbuseIPDB {ab['abuse_score']}/100")
    vt = live.get("VirusTotal")
    if vt and vt.get("ok") and vt.get("malicious") is not None:
        tot = sum(v for v in (vt.get("malicious"), vt.get("suspicious"),
                              vt.get("harmless"), vt.get("undetected")) if isinstance(v, int))
        bits.append(f"VT {vt['malicious']}/{tot}" if tot else f"VT mal {vt['malicious']}")
    sh = live.get("Shodan")
    if sh and sh.get("ok") and sh.get("ports"):
        bits.append(f"{len(sh['ports'])} porte")
    return " · ".join(bits) or "—"


def _summary_table(entities: list, live_by_value: dict, risk_by_value: dict, styles: dict):
    head = [Paragraph(escape(h), styles["cell_head"]) for h in
            ("Indicatore", "Tipo", "Confid.", "Rischio", "Punteggi chiave")]
    rows = [head]
    for e in entities:
        val = e["value"]
        risk = risk_by_value.get(val) or {}
        rows.append([
            Paragraph(escape(val), styles["mono_val"]),
            Paragraph(escape(e.get("type", "")), styles["kv_val"]),
            Paragraph(escape(e.get("confidence", "medium")), styles["kv_val"]),
            Paragraph(escape((risk.get("level") or "—")), styles["kv_val"]),
            Paragraph(escape(_key_scores(live_by_value.get(val) or {})), styles["kv_val"]),
        ])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), POE_ORANGE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, POE_HAIR),
    ]
    for r in range(1, len(rows)):
        if r % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, r), (-1, r), POE_ZEBRA))
    widths = [4.8 * cm, 1.9 * cm, 1.7 * cm, 2.0 * cm, _CONTENT_WIDTH - 10.4 * cm]
    return Table(rows, colWidths=widths, style=TableStyle(style_cmds), repeatRows=1)


# ── Header/footer brandizzati (ogni pagina) ──────────────────────────────────

def _make_page_decorator(header_right: str, footer_left: str, tlp: str = "TLP:CLEAR"):
    def _decorate(canv: canvas.Canvas, doc) -> None:
        w, h = A4
        canv.saveState()
        # Banda header scura calda POE + riga accento ambra sotto: brand
        # "POE_" (con underscore, firma della UI) in mono ambra su bruno scuro.
        band_h = 0.95 * cm
        canv.setFillColor(POE_INK)
        canv.rect(0, h - band_h, w, band_h, stroke=0, fill=1)
        canv.setFillColor(POE_ORANGE)
        canv.rect(0, h - band_h - 0.06 * cm, w, 0.06 * cm, stroke=0, fill=1)
        canv.setFont(_FONT_MONO_BOLD, 11)
        canv.setFillColor(POE_ORANGE)
        canv.drawString(_MARGIN, h - 0.62 * cm, "POE_")
        canv.setFont(_FONT_MONO, 7.5)
        canv.setFillColor(POE_CREAM)
        canv.drawString(_MARGIN + 1.25 * cm, h - 0.60 * cm, "PERSONAL OBSERVATION ENGINE")
        canv.setFillColor(colors.HexColor("#d4c8b0"))
        canv.drawRightString(w - _MARGIN, h - 0.60 * cm, header_right)
        # Footer: fonte a sx, Pagina X di Y al centro, marker TLP a dx.
        canv.setStrokeColor(POE_HAIR)
        canv.line(_MARGIN, 1.15 * cm, w - _MARGIN, 1.15 * cm)
        canv.setFont(_FONT_MONO, 7)
        canv.setFillColor(POE_SLATE)
        canv.drawString(_MARGIN, 0.8 * cm, footer_left)
        canv.drawCentredString(w / 2, 0.8 * cm, f"Pagina {canv.getPageNumber()} di {{total}}")
        canv.setFont(_FONT_MONO_BOLD, 7.5)
        canv.setFillColor(POE_AMBER_DK)
        canv.drawRightString(w - _MARGIN, 0.8 * cm, tlp)
        canv.restoreState()
    return _decorate


class _NumberedCanvas(canvas.Canvas):
    """Rimpiazza "{total}" nel footer col numero totale di pagine (noto solo
    a fine documento) — pattern standard: accumula gli stati pagina e li
    riscrive in save()."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._replace_total(total)
            super().showPage()
        super().save()

    def _replace_total(self, total: int) -> None:
        # I decorator disegnano "Pagina X di {total}" come testo statico; qui
        # non possiamo editare testo già disegnato, quindi il totale viene
        # ridisegnato coprendo il placeholder. Semplice e affidabile: ridisegna
        # la stringa centrata completa sopra quella col placeholder.
        w = A4[0]
        self.saveState()
        self.setFillColor(colors.white)
        self.rect(w / 2 - 2.2 * cm, 0.72 * cm, 4.4 * cm, 0.32 * cm, stroke=0, fill=1)
        self.setFillColor(POE_SLATE)
        self.setFont(_FONT_MONO, 7)
        self.drawCentredString(w / 2, 0.8 * cm, f"Pagina {self._pageNumber} di {total}")
        self.restoreState()


def build_pdf_report(
    obs: dict,
    risk_by_value: dict | None = None,
    observation_risk: dict | None = None,
    pivot_info: dict | None = None,
    live_results_by_value: dict | None = None,
    analysis_text: str | None = None,
    analysis_model: str | None = None,
) -> bytes:
    """PDF investigativo brandizzato POE: header/footer, title block, badge
    verdetto, tabella riepilogo indicatori, enrichment/tool live in tabelle,
    correlazioni, sintesi salvata e analisi investigativa LLM (markdown reso).
    Sempre scaricabile anche senza analisi (nota esplicita)."""
    risk_by_value = risk_by_value or {}
    pivot_info = pivot_info or {}
    live_results_by_value = live_results_by_value or {}
    s = _pdf_styles()

    obs_id = obs["id"]
    label = obs.get("label") or f"Osservazione #{obs_id}"
    entities = obs.get("entities", [])
    primary = entities[0]["value"] if entities else label
    score = compute_score(entities)
    accuracy = compute_accuracy(entities)
    ts = obs.get("timestamp", "")
    overall = (observation_risk or {}).get("overall_level")

    story: list = []
    story.append(Paragraph(f"Rapporto Investigativo — <font face='{_FONT_MONO}'>{escape(primary)}</font>", s["title"]))
    story.append(Paragraph(
        f"{escape(label)} · ID #{obs_id} · {escape(ts)} · Score {score} · Accuratezza ~{accuracy}%",
        s["meta"]))
    story.append(Spacer(1, 0.25 * cm))
    story.append(HRFlowable(width="100%", color=POE_ORANGE, thickness=1.2))
    story.append(Spacer(1, 0.3 * cm))

    # Verdetto / badge severità.
    story.append(_severity_badge(overall, s))
    if observation_risk and observation_risk.get("counts"):
        c = observation_risk["counts"]
        parts = [f"{c[k]} {lbl}" for k, lbl in
                 (("critico", "critici"), ("sospetto", "sospetti"), ("basso", "bassi")) if c.get(k)]
        if parts:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph("Rischio osservazione: " + " · ".join(parts), s["meta"]))

    # Sintesi esecutiva (BLUF), se presente.
    synthesis_text = obs.get("synthesis_text")
    if synthesis_text:
        story.append(_section("Sintesi esecutiva", s))
        story.append(Paragraph(f"Generata da {escape(obs.get('synthesis_model') or 'unknown')}", s["meta"]))
        story.extend(markdown_to_flowables(synthesis_text, s))

    # Tabella riepilogo indicatori.
    if entities:
        story.append(_section("Riepilogo indicatori", s))
        story.append(_summary_table(entities, live_results_by_value, risk_by_value, s))

    # Input originale.
    story.append(_section("Input originale", s))
    story.append(Preformatted(obs.get("raw_input", ""), s["raw"]))

    # Enrichment per entità (tabelle passive + una tabella per fonte live).
    story.append(_section("Dettaglio arricchimento", s))
    for type_name, items in group_by_type(entities).items():
        for item in items:
            val = item["value"]
            risk = risk_by_value.get(val) or {}
            risk_note = f" — rischio: {risk['level']}" if risk.get("level") else ""
            story.append(Paragraph(f"<font face='{_FONT_MONO}'>{escape(val)}</font>{escape(risk_note)}", s["h3"]))
            meta_pairs = _format_raw_dict(item.get("metadata") or {})
            if meta_pairs:
                story.append(_kv_table(meta_pairs, s, header="Enrichment automatico", header_color=POE_SLATE))
            for source_name, result in (live_results_by_value.get(val) or {}).items():
                pairs = _format_raw_dict(result)
                if pairs:
                    story.append(Spacer(1, 0.12 * cm))
                    story.append(_kv_table(pairs, s, header=source_name, header_color=POE_INK))
            story.append(Spacer(1, 0.25 * cm))

    # Correlazioni.
    correlated = [(v, info) for v, info in pivot_info.items() if info.get("count", 0) >= 2]
    if correlated:
        story.append(_section("Correlazioni", s))
        for v, info in correlated:
            others = ", ".join(f"#{i}" for i in info.get("other_observation_ids", []))
            story.append(Paragraph(
                f"<font face='{_FONT_MONO}'>{escape(v)}</font> — visto in {info['count']} osservazioni ({escape(others)})",
                s["body"]))

    # Analisi investigativa AI (markdown -> flowable).
    story.append(_section("Analisi Investigativa AI", s))
    if analysis_text and analysis_text.strip():
        story.append(Paragraph(f"Generata da {escape(analysis_model or 'unknown')}", s["meta"]))
        story.extend(markdown_to_flowables(analysis_text, s))
    else:
        story.append(Paragraph(
            "Non disponibile (modello LLM non caricato o errore di generazione) "
            "— mostrato solo il report dati.", s["body"]))

    # Fonti & metodologia.
    queried = sorted({name for v in live_results_by_value.values() for name in v})
    story.append(_section("Fonti & metodologia", s))
    story.append(Paragraph(
        "Tool interrogati: " + (", ".join(queried) if queried else "solo enrichment automatico")
        + ". Analista: POE (automated). I dati riflettono lo stato al momento dell'interrogazione.",
        s["meta"]))

    decorate = _make_page_decorator(header_right=f"#{obs_id} · {primary}",
                                    footer_left=f"POE · #{obs_id} · {ts[:10]}")
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=f"POE — {label}",
        topMargin=1.6 * cm, bottomMargin=1.5 * cm, leftMargin=_MARGIN, rightMargin=_MARGIN,
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
