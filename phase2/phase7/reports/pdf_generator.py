import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

PDF_OUTPUT_DIR = os.environ.get("REPORTS_PDF_DIR", "/mnt/reports_pdfs")
styles = getSampleStyleSheet()
h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=12)
h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceAfter=8)
body = styles["BodyText"]

def _to_flowables(content: str):
    flowables, bullets = [], []
    def flush():
        if bullets:
            flowables.append(ListFlowable(
                [ListItem(Paragraph(b, body)) for b in bullets], bulletType="bullet"))
            bullets.clear()
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            flush(); flowables.append(Spacer(1, 6)); continue
        if line.startswith("## "):
            flush(); flowables.append(Paragraph(line[3:], h2))
        elif line.startswith("# "):
            flush(); flowables.append(Paragraph(line[2:], h1))
        elif line.startswith("- "):
            bullets.append(line[2:])
        else:
            flush(); flowables.append(Paragraph(line, body))
    flush()
    return flowables

def generate_pdf(report_id: str, content: str) -> str:
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{report_id}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=LETTER, topMargin=0.75*inch, bottomMargin=0.75*inch)
    doc.build(_to_flowables(content))
    return pdf_path