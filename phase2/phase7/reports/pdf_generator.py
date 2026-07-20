"""
Phase 7 — pdf_generator.py

Converts the plain-text executive report produced by Phase 6 into a
styled PDF suitable for delivery to a customer contact.

Design goals:
  - Professional executive-report aesthetic without external fonts or
    assets (ReportLab only, no internet dependency at render time).
  - Clear visual hierarchy: dark branded header → KPI summary strip →
    colour-coded section headings → readable body → citation callouts →
    page footer.
  - All styling is defined once at module level so it's easy to tweak
    (colours, fonts, margins) without touching the parsing logic.
"""

import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ─── Output directory ────────────────────────────────────────────────────────

PDF_OUTPUT_DIR = os.environ.get("REPORTS_PDF_DIR", "/mnt/reports_pdfs")

# ─── Colour palette ──────────────────────────────────────────────────────────

NAVY       = colors.HexColor("#0D1B2A")   # header / section label bg
STEEL      = colors.HexColor("#1E3A5F")   # sub-heading accent
ACCENT     = colors.HexColor("#2196F3")   # rule / bullet accent
LIGHT_GREY = colors.HexColor("#F5F7FA")   # callout bg
MID_GREY   = colors.HexColor("#9AA5B4")   # footer / caption text
DARK_TEXT  = colors.HexColor("#1A1A2E")   # primary body text
WHITE      = colors.white


# ─── Typography ──────────────────────────────────────────────────────────────
# Uses Helvetica (built-in, no file dependency).

_base = getSampleStyleSheet()

STYLE_BODY = ParagraphStyle(
    "SCBody",
    fontName="Helvetica",
    fontSize=9.5,
    leading=15,
    textColor=DARK_TEXT,
    spaceAfter=4,
)

STYLE_SECTION_HEADER = ParagraphStyle(
    "SCSectionHeader",
    fontName="Helvetica-Bold",
    fontSize=11,
    leading=14,
    textColor=WHITE,
    spaceAfter=0,
    leftIndent=8,
)

STYLE_H2 = ParagraphStyle(
    "SCH2",
    fontName="Helvetica-Bold",
    fontSize=10,
    leading=13,
    textColor=STEEL,
    spaceBefore=10,
    spaceAfter=4,
)

STYLE_H3 = ParagraphStyle(
    "SCH3",
    fontName="Helvetica-BoldOblique",
    fontSize=9.5,
    leading=13,
    textColor=STEEL,
    spaceBefore=8,
    spaceAfter=3,
)

STYLE_CITATION = ParagraphStyle(
    "SCCitation",
    fontName="Courier",
    fontSize=7.5,
    leading=10,
    textColor=STEEL,
    backColor=LIGHT_GREY,
    spaceAfter=2,
    leftIndent=6,
    rightIndent=6,
)

STYLE_CALLOUT = ParagraphStyle(
    "SCCallout",
    fontName="Helvetica-Oblique",
    fontSize=9,
    leading=13,
    textColor=DARK_TEXT,
    backColor=LIGHT_GREY,
    leftIndent=10,
    rightIndent=6,
    spaceBefore=6,
    spaceAfter=6,
)

STYLE_HEADER_TITLE = ParagraphStyle(
    "SCHeaderTitle",
    fontName="Helvetica-Bold",
    fontSize=16,
    leading=20,
    textColor=WHITE,
    alignment=TA_LEFT,
)

STYLE_HEADER_SUB = ParagraphStyle(
    "SCHeaderSub",
    fontName="Helvetica",
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#90CAF9"),
    alignment=TA_LEFT,
)

STYLE_KPI_VALUE = ParagraphStyle(
    "SCKpiValue",
    fontName="Helvetica-Bold",
    fontSize=15,
    textColor=NAVY,
    alignment=TA_LEFT,
)

STYLE_KPI_LABEL = ParagraphStyle(
    "SCKpiLabel",
    fontName="Helvetica",
    fontSize=7.5,
    textColor=MID_GREY,
    alignment=TA_LEFT,
)


# ─── Citation pattern (hex IDs inline in text) ───────────────────────────────

_CITE_RE = re.compile(r"\[([a-f0-9]{16,})\]")


def _highlight_citations(text: str) -> str:
    """Wrap inline citation markers in a small coloured span for ReportLab."""
    return _CITE_RE.sub(
        lambda m: (
            f'<font color="#2196F3" face="Courier" size="7">'
            f"[{m.group(1)[:8]}&#8230;]</font>"
        ),
        text,
    )


# ─── Severity word highlighting ──────────────────────────────────────────────

_SEVERITY_WORD_RE = re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b")
_SEVERITY_WORD_HEX = {
    "CRITICAL": "#C62828",
    "HIGH":     "#EF6C00",
    "MEDIUM":   "#F9A825",
    "LOW":      "#2E7D32",
}


def _highlight_severity(text: str) -> str:
    """Colour standalone severity words (CRITICAL/HIGH/MEDIUM/LOW) inline."""
    return _SEVERITY_WORD_RE.sub(
        lambda m: f'<font color="{_SEVERITY_WORD_HEX[m.group(1)]}"><b>{m.group(1)}</b></font>',
        text,
    )


def _style(text: str) -> str:
    """Apply both inline highlighters in the standard order."""
    return _highlight_severity(_highlight_citations(text))


# ─── Section header block ────────────────────────────────────────────────────

_SECTION_COLOURS = {
    "EXECUTIVE VERDICT": NAVY,
    "THEMES":            STEEL,
    "APPENDIX":          colors.HexColor("#374151"),
}

_KNOWN_SECTIONS = set(_SECTION_COLOURS.keys())


def _section_header_table(title: str) -> Table:
    """Dark banner row used for top-level section titles."""
    bg = _SECTION_COLOURS.get(title, NAVY)
    tbl = Table(
        [[Paragraph(title, STYLE_SECTION_HEADER)]],
        colWidths=["100%"],
    )
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), bg),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ])
    )
    return tbl


# ─── Cover / page header ─────────────────────────────────────────────────────

def _build_cover_header(report_id: str) -> list:
    """Full-width dark banner at the top of page 1."""
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    tbl = Table(
        [[
            Paragraph("Supply Chain Risk Monitor", STYLE_HEADER_TITLE),
            Paragraph(
                f"Executive Report<br/>"
                f"<font size='8'>{report_id}</font><br/>"
                f"<font size='8'>Generated {generated}</font>",
                STYLE_HEADER_SUB,
            ),
        ]],
        colWidths=["55%", "45%"],
    )
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    return [tbl, Spacer(1, 14)]


# ─── KPI summary strip ───────────────────────────────────────────────────────

def _kpi_cell(label: str, value: str) -> Table:
    t = Table(
        [[Paragraph(value, STYLE_KPI_VALUE)], [Paragraph(label, STYLE_KPI_LABEL)]],
        colWidths=["100%"],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    return t


def _build_kpi_strip(incident_count, theme_count, escalation_rate, status) -> list:
    """Four-box KPI row: incidents, themes, escalation rate, status.
    Returns [] if no metrics were supplied — caller can omit entirely."""
    if incident_count is None and theme_count is None and escalation_rate is None:
        return []

    status_hex = "#2E7D32" if status == "ok" else "#EF6C00"
    status_label = "OK" if status == "ok" else "NEEDS REVIEW"

    row = Table(
        [[
            _kpi_cell("INCIDENTS", str(incident_count if incident_count is not None else "—")),
            _kpi_cell("THEMES", str(theme_count if theme_count is not None else "—")),
            _kpi_cell("ESCALATION RATE",
                      f"{escalation_rate:.0%}" if escalation_rate is not None else "—"),
            _kpi_cell("STATUS", f'<font color="{status_hex}">{status_label}</font>'),
        ]],
        colWidths=["25%", "25%", "25%", "25%"],
    )
    row.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [row, Spacer(1, 12)]


# ─── Content parser ──────────────────────────────────────────────────────────

def _to_flowables(
    report_id: str,
    content: str,
    incident_count=None,
    theme_count=None,
    escalation_rate=None,
    status=None,
) -> list:
    flowables: list = []
    flowables.extend(_build_cover_header(report_id))
    flowables.extend(_build_kpi_strip(incident_count, theme_count, escalation_rate, status))

    bullets: list[str] = []

    def flush_bullets():
        if bullets:
            flowables.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(_style(b), STYLE_BODY),
                            bulletColor=ACCENT,
                            bulletType="bullet",
                            bulletFontSize=8,
                        )
                        for b in bullets
                    ],
                    bulletType="bullet",
                    leftIndent=16,
                    spaceAfter=4,
                )
            )
            bullets.clear()

    for raw in content.splitlines():
        line = raw.strip()

        # blank line
        if not line:
            flush_bullets()
            flowables.append(Spacer(1, 5))
            continue

        # top-level section banner (EXECUTIVE VERDICT / THEMES / APPENDIX)
        canonical = line.rstrip(":")
        if canonical in _KNOWN_SECTIONS:
            flush_bullets()
            flowables.append(Spacer(1, 10))
            flowables.append(_section_header_table(canonical))
            flowables.append(Spacer(1, 8))
            continue

        # markdown H1
        if line.startswith("# "):
            flush_bullets()
            flowables.append(Paragraph(_style(line[2:]), STYLE_H2))
            flowables.append(
                HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4)
            )
            continue

        # markdown H2
        if line.startswith("## "):
            flush_bullets()
            flowables.append(Paragraph(_style(line[3:]), STYLE_H2))
            continue

        # markdown H3
        if line.startswith("### "):
            flush_bullets()
            flowables.append(Paragraph(_style(line[4:]), STYLE_H3))
            continue

        # bullet
        if line.startswith("- ") or line.startswith("* "):
            bullets.append(line[2:])
            continue

        # appendix assessment entry (e.g. "assessment_abc123: …")
        if re.match(r"^assessment_\w+\s*:", line, re.IGNORECASE):
            flush_bullets()
            flowables.append(Paragraph(_style(line), STYLE_CITATION))
            continue

        # escalation rate sentence → styled callout box
        if "escalation rate" in line.lower():
            flush_bullets()
            flowables.append(Paragraph(_style(line), STYLE_CALLOUT))
            continue

        # plain body paragraph
        flush_bullets()
        flowables.append(Paragraph(_style(line), STYLE_BODY))

    flush_bullets()
    return flowables


# ─── Page template with footer ───────────────────────────────────────────────

class _FooterDocTemplate(BaseDocTemplate):
    """BaseDocTemplate subclass that draws a footer rule + page number."""

    def __init__(self, filename: str, report_id: str, **kwargs):
        self._report_id = report_id
        super().__init__(filename, **kwargs)
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="main",
        )
        self.addPageTemplates(
            [PageTemplate(id="main", frames=frame, onPage=self._draw_footer)]
        )

    def _draw_footer(self, canvas, doc):
        canvas.saveState()
        y = doc.bottomMargin - 16
        canvas.setStrokeColor(MID_GREY)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, y + 10, doc.width + doc.leftMargin, y + 10)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MID_GREY)
        canvas.drawString(
            doc.leftMargin,
            y,
            f"Supply Chain Risk Monitor  |  {self._report_id}  |  CONFIDENTIAL",
        )
        canvas.drawRightString(
            doc.width + doc.leftMargin,
            y,
            f"Page {doc.page}",
        )
        canvas.restoreState()


# ─── Public entry point ──────────────────────────────────────────────────────

def generate_pdf(
    report_id: str,
    content: str,
    incident_count=None,
    theme_count=None,
    escalation_rate=None,
    status=None,
) -> str:
    """
    Convert plain-text report content to a styled PDF.

    Args:
        report_id: Unique report identifier (used in filename + footer).
        content:   Plain-text report as produced by Phase 6 / Groq.
        incident_count/theme_count/escalation_rate/status: optional —
            when provided (from ExecutiveReport's own properties), render
            as a KPI summary strip below the cover header.

    Returns:
        Absolute path to the generated PDF file.
    """
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{report_id}.pdf")

    doc = _FooterDocTemplate(
        pdf_path,
        report_id=report_id,
        pagesize=LETTER,
        topMargin=0.6 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
    )
    doc.build(_to_flowables(
        report_id, content, incident_count, theme_count, escalation_rate, status,
    ))
    return pdf_path