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

        # --- derive severity labels ---
        initial_sev = (ctx.get("initial_severity") or "unknown").upper()
        final_sev = (ctx.get("severity") or initial_sev).upper()
        conf_raw = ctx.get("confidence") or 0
        conf_pct = int(round(conf_raw * 100)) if isinstance(conf_raw, float) else int(conf_raw)
        conf_label = "High" if conf_pct >= 80 else "Medium" if conf_pct >= 50 else "Low"

        event_title = ctx.get("event_title") or (ctx.get("event_titles") or [""])[0] or "Supply-chain disruption"
        customer_id = ctx.get("customer_id", "")
        supplier_id = ctx.get("supplier_id", "")

        # --- subject ---
        if needs_review:
            msg["Subject"] = (
                f"[{final_sev} — PENDING REVIEW] {event_title} — {ctx['company_name']}"
            )
        else:
            msg["Subject"] = f"[{final_sev}] {event_title} — {ctx['company_name']}"

        msg["From"] = SMTP_USER
        msg["To"] = ctx["contact_email"]

        # --- headline ---
        headline = f"{final_sev} — {event_title}"
        if customer_id:
            headline += f" — customer={customer_id}"
        if supplier_id:
            headline += f" via supplier={supplier_id}"
        if initial_sev != final_sev and initial_sev != "UNKNOWN":
            headline += f"  [Initial: {initial_sev} → Reassessed: {final_sev}]"

        lines: list[str] = []

        if needs_review:
            lines.append(
                "NOTE: This assessment could not be fully validated by our analysis "
                "engine and is pending human review. The severity below reflects "
                "our upstream disruption-matching signal, not a confirmed AI assessment."
            )
            lines.append("")

        lines.append(headline)
        lines.append(f"Confidence: {conf_label} ({conf_pct}%) | Updated: {ctx.get('updated_at', 'N/A')}")
        lines.append("")

        # --- affected products ---
        products = ctx.get("affected_product_ids") or []
        lines.append(
            "Affected products: " + (", ".join(products) if products else "none identified")
        )
        lines.append("")

        # --- impact ---
        lines.append(f"Impact: {ctx.get('predicted_business_impact', 'N/A')}")
        lines.append("")

        # --- evidence ---
        evidence = ctx.get("evidence") or []
        if evidence:
            lines.append("Evidence:")
            for e in evidence:
                lines.append(f"  • {e}")
        else:
            lines.append("Evidence: none returned by model — treat impact statement as unverified")
        lines.append("")

        # --- recommended actions ---
        actions = json.loads(ctx.get("recommended_actions_json") or "[]")
        if actions:
            lines.append("Recommended actions:")
            for a in actions:
                if isinstance(a, dict):
                    urgency = a.get("urgency", "?").upper()
                    action_text = a.get("action", "")
                    rationale = a.get("rationale", "")
                    lines.append(f"  [{urgency}] {action_text}")
                    if rationale:
                        lines.append(f"      → {rationale}")
                else:
                    lines.append(f"  - {a}")

        lines.append("------------------------------------------------------------")
        lines.append(f"Assessment ID: {ctx['assessment_id']}")

        msg.set_content("\n".join(lines))
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