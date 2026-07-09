import os
import json
import smtplib
from email.message import EmailMessage
from .base import DeliveryChannel

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_APP_PASSWORD = os.environ["SMTP_APP_PASSWORD"]

class EmailDelivery(DeliveryChannel):
    def _send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.send_message(msg)

    def send_alert(self, ctx: dict, needs_review: bool = False) -> None:
        msg = EmailMessage()
        severity_label = (ctx.get("initial_severity") or "unknown").upper()
        if needs_review:
            msg["Subject"] = f"[{severity_label} — PENDING REVIEW] Possible supply chain issue — {ctx['company_name']}"
            banner = (
                "NOTE: This assessment could not be fully validated by our analysis "
                "engine and is pending human review. The severity below reflects "
                "our upstream disruption-matching signal, not a confirmed AI assessment.\n\n"
            )
        else:
            msg["Subject"] = f"[{severity_label}] Supply chain alert — {ctx['company_name']}"
            banner = ""
        msg["From"] = SMTP_USER
        msg["To"] = ctx["contact_email"]

        actions = json.loads(ctx.get("recommended_actions_json") or "[]")
        lines = [
            banner.strip(),
            f"Severity: {severity_label}  (confidence: {ctx.get('confidence')})",
            f"Predicted business impact: {ctx.get('predicted_business_impact')}",
            "", "Source events:",
            *[f"  - {t}" for t in ctx.get("event_titles", []) if t],
            "", "Evidence:",
            *[f"  - {e}" for e in (ctx.get("evidence") or [])],
            "", "Recommended actions:",
            *[f"  - {a}" for a in actions],
            "", f"Assessment ID: {ctx['assessment_id']}",
        ]
        msg.set_content("\n".join(filter(None, lines)))
        self._send(msg)

    def send_alert(self, contact_email: str, company_name: str, body_text: str,
               severity: str, needs_review: bool = False) -> None:
        msg = EmailMessage()
        sev_label = (severity or "unknown").upper()
        subject = f"[{sev_label}] Supply chain alert — {company_name}"
        if needs_review:
            subject = f"[{sev_label} — PENDING REVIEW] " + subject[subject.index("]")+2:]
            body_text = (
                "NOTE: This assessment could not be fully validated and is pending "
                "human review. Treat the details below as unconfirmed.\n\n" + body_text
            )
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = contact_email
        msg.set_content(body_text)
        self._send(msg)

    def send_report(self, report_context: dict, pdf_path: str) -> None:
        msg = EmailMessage()
        company = report_context.get("company_name", "your company")
        period_start = report_context.get("period_start", "")
        period_end = report_context.get("period_end", "")
        incident_count = report_context.get("incident_count", 0)
        theme_count = report_context.get("theme_count", 0)
        escalation_rate = report_context.get("escalation_rate", 0)
        contact_email = report_context["contact_email"]

        msg["Subject"] = f"Executive Supply Chain Report — {company} ({period_start} to {period_end})"
        msg["From"] = SMTP_USER
        msg["To"] = contact_email

        body = (
            f"Dear {company} team,\n\n"
            f"Please find attached your executive supply chain report for the period "
            f"{period_start} to {period_end}.\n\n"
            f"Summary:\n"
            f"  - Total incidents:    {incident_count}\n"
            f"  - Distinct themes:    {theme_count}\n"
            f"  - Escalation rate:    {escalation_rate:.1%}\n\n"
            "The full report is attached as a PDF.\n\n"
            "Regards,\nSupply Chain Monitor"
        )
        msg.set_content(body)

        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        msg.add_attachment(pdf_data, maintype="application", subtype="pdf",
                           filename=f"report_{period_start}_{period_end}.pdf")

        self._send(msg)