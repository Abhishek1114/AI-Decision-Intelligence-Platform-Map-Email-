from phase2.phase7.reports.pdf_generator import generate_pdf
from phase2.phase7.delivery.email_delivery import EmailDelivery

FETCH_REPORT_FOR_PDF = """
MATCH (r:ExecutiveReport {report_id: $report_id})
MATCH (c:Customer {customer_id: r.customer_id})
RETURN r.content AS content, r.period_start AS period_start, r.period_end AS period_end,
       r.incident_count AS incident_count, r.theme_count AS theme_count,
       r.escalation_rate AS escalation_rate,
       c.company_name AS company_name, c.contact_email AS contact_email
"""

SET_PDF_PATH = """
MATCH (r:ExecutiveReport {report_id: $report_id})
SET r.pdf_path = $pdf_path
"""

def generate_and_send_report_pdf(session, report_id: str, customer_id: str) -> None:
    record = session.run(FETCH_REPORT_FOR_PDF, parameters={"report_id": report_id}).single()
    if record is None:
        print(f"Could not re-fetch {report_id} for PDF generation — skipping")
        return

    pdf_path = generate_pdf(report_id, record["content"])
    session.run(SET_PDF_PATH, parameters={"report_id": report_id, "pdf_path": pdf_path})

    if not record["contact_email"]:
        print(f"Customer {customer_id} has no contact_email — PDF generated, email skipped")
        return

    EmailDelivery().send_report(
        {
            "company_name": record["company_name"],
            "period_start": record["period_start"],
            "period_end": record["period_end"],
            "incident_count": record["incident_count"],
            "theme_count": record["theme_count"],
            "escalation_rate": record["escalation_rate"],
            "contact_email": record["contact_email"],
        },
        pdf_path,
    )