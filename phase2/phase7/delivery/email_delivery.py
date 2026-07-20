import os
import json
import smtplib
from email.message import EmailMessage
from .base import DeliveryChannel

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_APP_PASSWORD = os.environ["SMTP_APP_PASSWORD"]

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
_SEVERITY_COLORS = {
    "CRITICAL": ("#e74c3c", "#fdecea"),
    "HIGH":     ("#e67e22", "#fef5e7"),
    "MEDIUM":   ("#f39c12", "#fef9e7"),
    "LOW":      ("#3498db", "#eaf2f8"),
}

_URGENCY_COLORS = {
    "IMMEDIATE": "#e74c3c",
    "24H":       "#e67e22",
    "48H":       "#f39c12",
    "WEEK":      "#3498db",
}

_FONT_STACK = "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


class EmailDelivery(DeliveryChannel):
    def _send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.send_message(msg)

    # -----------------------------------------------------------------------
    #  ALERT — HTML builder
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_alert_html(ctx: dict, needs_review: bool) -> str:
        initial_sev = (ctx.get("initial_severity") or "unknown").upper()
        final_sev = (ctx.get("severity") or initial_sev).upper()
        conf_raw = ctx.get("confidence") or 0
        conf_pct = int(round(conf_raw * 100)) if isinstance(conf_raw, float) else int(conf_raw)
        conf_label = "High" if conf_pct >= 80 else "Medium" if conf_pct >= 50 else "Low"

        event_title = ctx.get("event_title") or (ctx.get("event_titles") or [""])[0] or "Supply-chain disruption"
        customer_id = ctx.get("customer_id", "")
        supplier_id = ctx.get("supplier_id", "")
        company_name = ctx.get("company_name", "")

        sev_color, sev_bg = _SEVERITY_COLORS.get(final_sev, ("#95a5a6", "#f0f0f0"))

        # --- reassessment note ---
        reassess_html = ""
        if initial_sev != final_sev and initial_sev != "UNKNOWN":
            reassess_html = f"""
            <tr><td style="padding:8px 24px 16px 24px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
                <td style="background:#2c3e50;color:#ecf0f1;padding:10px 16px;border-radius:6px;
                           font-size:13px;font-family:{_FONT_STACK};">
                  ⚡ Severity reassessed from
                  <strong style="color:#f39c12;">{initial_sev}</strong> →
                  <strong style="color:{sev_color};">{final_sev}</strong>
                </td>
              </tr></table>
            </td></tr>"""

        # --- pending-review banner ---
        review_html = ""
        if needs_review:
            review_html = f"""
            <tr><td style="padding:8px 24px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
                <td style="background:#fff3cd;border-left:4px solid #ffc107;padding:14px 18px;
                           border-radius:0 6px 6px 0;font-family:{_FONT_STACK};font-size:13px;color:#856404;">
                  ⏳ <strong>Pending Human Review</strong><br/>
                  This assessment could not be fully validated by our analysis engine.
                  The severity reflects the upstream disruption-matching signal, not a confirmed AI assessment.
                </td>
              </tr></table>
            </td></tr>"""

        # --- confidence bar ---
        bar_color = "#2ecc71" if conf_pct >= 80 else "#f39c12" if conf_pct >= 50 else "#e74c3c"
        confidence_html = f"""
        <tr><td style="padding:12px 24px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="font-family:{_FONT_STACK};font-size:13px;color:#7f8c8d;padding-bottom:6px;">
                Confidence: <strong style="color:#2c3e50;">{conf_label} ({conf_pct}%)</strong>
                &nbsp;&nbsp;|&nbsp;&nbsp;Updated: {ctx.get('updated_at', 'N/A')}
              </td>
            </tr>
            <tr>
              <td>
                <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-radius:10px;overflow:hidden;">
                  <tr>
                    <td style="background:{bar_color};height:8px;width:{conf_pct}%;border-radius:10px 0 0 10px;"></td>
                    <td style="background:#ecf0f1;height:8px;width:{100-conf_pct}%;border-radius:0 10px 10px 0;"></td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td></tr>"""

        # --- entity info ---
        entity_parts = []
        if customer_id:
            entity_parts.append(f"<strong>Customer:</strong> {customer_id}")
        if supplier_id:
            entity_parts.append(f"<strong>Supplier:</strong> {supplier_id}")
        entity_html = ""
        if entity_parts:
            entity_html = f"""
            <tr><td style="padding:4px 24px 8px 24px;">
              <table cellpadding="0" cellspacing="0" border="0"><tr>
                <td style="font-family:{_FONT_STACK};font-size:12px;color:#95a5a6;">
                  {'&nbsp;&nbsp;·&nbsp;&nbsp;'.join(entity_parts)}
                </td>
              </tr></table>
            </td></tr>"""

        # --- affected products ---
        products = ctx.get("affected_product_ids") or []
        if products:
            pills = "".join(
                f'<td style="background:#eaf2f8;color:#2980b9;padding:5px 12px;border-radius:20px;'
                f'font-size:12px;font-family:{_FONT_STACK};margin-right:6px;border:1px solid #d4e6f1;">'
                f'{p}</td><td width="6"></td>'
                for p in products
            )
            products_html = f"""
            <tr><td style="padding:12px 24px 4px 24px;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="font-family:{_FONT_STACK};font-size:11px;color:#95a5a6;
                             text-transform:uppercase;letter-spacing:1px;padding-bottom:8px;"
                      colspan="{len(products)*2}">Affected Products</td>
                </tr>
                <tr>{pills}</tr>
              </table>
            </td></tr>"""
        else:
            products_html = f"""
            <tr><td style="padding:12px 24px 4px 24px;">
              <span style="font-family:{_FONT_STACK};font-size:12px;color:#bdc3c7;">
                No specific products identified
              </span>
            </td></tr>"""

        # --- impact card ---
        impact = ctx.get("predicted_business_impact", "N/A")
        impact_html = f"""
        <tr><td style="padding:12px 24px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
            <td style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:18px 20px;
                       border-radius:10px;color:#ecf0f1;font-family:{_FONT_STACK};">
              <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
                             color:#00d2ff;padding-bottom:8px;">💥 Predicted Business Impact</td>
                </tr>
                <tr>
                  <td style="font-size:14px;line-height:1.6;color:#ecf0f1;">{impact}</td>
                </tr>
              </table>
            </td>
          </tr></table>
        </td></tr>"""

        # --- evidence ---
        evidence = ctx.get("evidence") or []
        if evidence:
            ev_rows = "".join(
                f'<tr><td style="padding:6px 0;font-size:13px;color:#34495e;font-family:{_FONT_STACK};'
                f'line-height:1.5;border-bottom:1px solid #f0f0f0;">'
                f'<span style="color:#00d2ff;margin-right:8px;">▸</span> {e}</td></tr>'
                for e in evidence
            )
            evidence_html = f"""
            <tr><td style="padding:12px 24px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr><td style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
                               color:#95a5a6;padding-bottom:10px;font-family:{_FONT_STACK};">
                  📋 Evidence
                </td></tr>
                {ev_rows}
              </table>
            </td></tr>"""
        else:
            evidence_html = f"""
            <tr><td style="padding:12px 24px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
                <td style="font-size:13px;color:#e74c3c;font-family:{_FONT_STACK};
                           background:#fdecea;padding:12px 16px;border-radius:6px;">
                  ⚠️ No evidence returned by model — treat impact statement as unverified
                </td>
              </tr></table>
            </td></tr>"""

        # --- recommended actions ---
        actions = json.loads(ctx.get("recommended_actions_json") or "[]")
        actions_html = ""
        if actions:
            action_rows = ""
            for a in actions:
                if isinstance(a, dict):
                    urgency = a.get("urgency", "?").upper()
                    u_color = _URGENCY_COLORS.get(urgency, "#95a5a6")
                    action_text = a.get("action", "")
                    rationale = a.get("rationale", "")
                    rationale_row = (
                        f'<br/><span style="color:#95a5a6;font-size:12px;font-style:italic;">'
                        f'↳ {rationale}</span>' if rationale else ""
                    )
                    action_rows += f"""
                    <tr>
                      <td style="padding:12px 14px;border-bottom:1px solid #f4f6f9;vertical-align:top;width:90px;">
                        <span style="background:{u_color};color:#fff;padding:3px 10px;border-radius:4px;
                                     font-size:11px;font-weight:bold;font-family:{_FONT_STACK};
                                     white-space:nowrap;">{urgency}</span>
                      </td>
                      <td style="padding:12px 14px;border-bottom:1px solid #f4f6f9;font-size:13px;
                                 color:#2c3e50;font-family:{_FONT_STACK};line-height:1.5;">
                        {action_text}{rationale_row}
                      </td>
                    </tr>"""
                else:
                    action_rows += f"""
                    <tr>
                      <td colspan="2" style="padding:10px 14px;border-bottom:1px solid #f4f6f9;
                                             font-size:13px;color:#2c3e50;font-family:{_FONT_STACK};">
                        • {a}
                      </td>
                    </tr>"""

            actions_html = f"""
            <tr><td style="padding:12px 24px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr><td style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
                               color:#95a5a6;padding-bottom:10px;font-family:{_FONT_STACK};">
                  🎯 Recommended Actions
                </td></tr>
                <tr><td>
                  <table cellpadding="0" cellspacing="0" border="0" width="100%"
                         style="background:#fff;border-radius:8px;border:1px solid #ecf0f1;overflow:hidden;">
                    {action_rows}
                  </table>
                </td></tr>
              </table>
            </td></tr>"""

        # --- assemble full HTML ---
        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:{_FONT_STACK};">

<!-- outer wrapper -->
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f6f9;">
<tr><td align="center" style="padding:24px 12px;">

  <!-- main card -->
  <table cellpadding="0" cellspacing="0" border="0" width="640"
         style="background:#ffffff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <!-- header -->
    <tr>
      <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
                 padding:28px 24px 20px 24px;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td>
              <span style="font-size:11px;text-transform:uppercase;letter-spacing:2px;
                           color:rgba(255,255,255,0.5);font-family:{_FONT_STACK};">
                Supply Chain Monitor
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:10px;">
              <span style="display:inline-block;background:{sev_color};color:#fff;
                           padding:5px 14px;border-radius:6px;font-size:12px;
                           font-weight:bold;letter-spacing:1px;font-family:{_FONT_STACK};">
                {final_sev}
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:12px;">
              <span style="font-size:22px;font-weight:700;color:#ffffff;
                           font-family:{_FONT_STACK};line-height:1.3;">
                {event_title}
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:6px;">
              <span style="font-size:14px;color:rgba(255,255,255,0.7);font-family:{_FONT_STACK};">
                {company_name}
              </span>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- review banner -->
    {review_html}

    <!-- reassessment note -->
    {reassess_html}

    <!-- confidence -->
    {confidence_html}

    <!-- entity info -->
    {entity_html}

    <!-- affected products -->
    {products_html}

    <!-- impact -->
    {impact_html}

    <!-- evidence -->
    {evidence_html}

    <!-- actions -->
    {actions_html}

    <!-- footer -->
    <tr>
      <td style="padding:20px 24px;border-top:1px solid #ecf0f1;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="font-size:11px;color:#bdc3c7;font-family:{_FONT_STACK};">
              Assessment ID: <span style="color:#95a5a6;">{ctx['assessment_id']}</span>
            </td>
            <td align="right" style="font-size:11px;color:#bdc3c7;font-family:{_FONT_STACK};">
              Powered by <strong style="color:#00d2ff;">Supply Chain Monitor</strong>
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table><!-- /main card -->

</td></tr>
</table><!-- /outer wrapper -->

</body>
</html>"""
        return html

    # -----------------------------------------------------------------------
    #  ALERT — plain-text builder (fallback)
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_alert_plain(ctx: dict, needs_review: bool) -> str:
        initial_sev = (ctx.get("initial_severity") or "unknown").upper()
        final_sev = (ctx.get("severity") or initial_sev).upper()
        conf_raw = ctx.get("confidence") or 0
        conf_pct = int(round(conf_raw * 100)) if isinstance(conf_raw, float) else int(conf_raw)
        conf_label = "High" if conf_pct >= 80 else "Medium" if conf_pct >= 50 else "Low"

        event_title = ctx.get("event_title") or (ctx.get("event_titles") or [""])[0] or "Supply-chain disruption"
        customer_id = ctx.get("customer_id", "")
        supplier_id = ctx.get("supplier_id", "")

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

        products = ctx.get("affected_product_ids") or []
        lines.append(
            "Affected products: " + (", ".join(products) if products else "none identified")
        )
        lines.append("")

        lines.append(f"Impact: {ctx.get('predicted_business_impact', 'N/A')}")
        lines.append("")

        evidence = ctx.get("evidence") or []
        if evidence:
            lines.append("Evidence:")
            for e in evidence:
                lines.append(f"  • {e}")
        else:
            lines.append("Evidence: none returned by model — treat impact statement as unverified")
        lines.append("")

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
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    #  REPORT — HTML builder
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_report_html(report_context: dict) -> str:
        company = report_context.get("company_name", "your company")
        period_start = report_context.get("period_start", "")
        period_end = report_context.get("period_end", "")
        incident_count = report_context.get("incident_count", 0)
        theme_count = report_context.get("theme_count", 0)
        escalation_rate = report_context.get("escalation_rate", 0)

        esc_pct = f"{escalation_rate:.1%}" if isinstance(escalation_rate, float) else str(escalation_rate)

        # color for escalation rate
        esc_color = "#e74c3c" if (isinstance(escalation_rate, float) and escalation_rate >= 0.3) else \
                    "#f39c12" if (isinstance(escalation_rate, float) and escalation_rate >= 0.15) else "#2ecc71"

        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:{_FONT_STACK};">

<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f6f9;">
<tr><td align="center" style="padding:24px 12px;">

  <table cellpadding="0" cellspacing="0" border="0" width="640"
         style="background:#ffffff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <!-- header -->
    <tr>
      <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
                 padding:28px 24px 24px 24px;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td>
              <span style="font-size:11px;text-transform:uppercase;letter-spacing:2px;
                           color:rgba(255,255,255,0.5);font-family:{_FONT_STACK};">
                Supply Chain Monitor
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:12px;">
              <span style="font-size:22px;font-weight:700;color:#ffffff;
                           font-family:{_FONT_STACK};line-height:1.3;">
                Executive Supply Chain Report
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:6px;">
              <span style="font-size:14px;color:rgba(255,255,255,0.7);font-family:{_FONT_STACK};">
                {company} &nbsp;·&nbsp; {period_start} to {period_end}
              </span>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- metric cards -->
    <tr>
      <td style="padding:24px 24px 8px 24px;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <!-- incidents -->
            <td width="33%" style="padding-right:8px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"
                     style="background:#f8f9fa;border-radius:10px;border:1px solid #ecf0f1;">
                <tr>
                  <td align="center" style="padding:18px 10px 6px 10px;">
                    <span style="font-size:28px;font-weight:800;color:#2c3e50;
                                 font-family:{_FONT_STACK};">{incident_count}</span>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:0 10px 16px 10px;">
                    <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                                 color:#95a5a6;font-family:{_FONT_STACK};">Incidents</span>
                  </td>
                </tr>
              </table>
            </td>
            <!-- themes -->
            <td width="33%" style="padding:0 4px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"
                     style="background:#f8f9fa;border-radius:10px;border:1px solid #ecf0f1;">
                <tr>
                  <td align="center" style="padding:18px 10px 6px 10px;">
                    <span style="font-size:28px;font-weight:800;color:#2c3e50;
                                 font-family:{_FONT_STACK};">{theme_count}</span>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:0 10px 16px 10px;">
                    <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                                 color:#95a5a6;font-family:{_FONT_STACK};">Themes</span>
                  </td>
                </tr>
              </table>
            </td>
            <!-- escalation rate -->
            <td width="33%" style="padding-left:8px;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"
                     style="background:#f8f9fa;border-radius:10px;border:1px solid #ecf0f1;">
                <tr>
                  <td align="center" style="padding:18px 10px 6px 10px;">
                    <span style="font-size:28px;font-weight:800;color:{esc_color};
                                 font-family:{_FONT_STACK};">{esc_pct}</span>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:0 10px 16px 10px;">
                    <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                                 color:#95a5a6;font-family:{_FONT_STACK};">Escalation Rate</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- body text -->
    <tr>
      <td style="padding:16px 24px;">
        <p style="font-size:14px;color:#34495e;line-height:1.7;font-family:{_FONT_STACK};margin:0;">
          Dear {company} team,
        </p>
        <p style="font-size:14px;color:#34495e;line-height:1.7;font-family:{_FONT_STACK};margin:12px 0 0 0;">
          Please find attached your executive supply chain report for the period
          <strong>{period_start}</strong> to <strong>{period_end}</strong>.
          The full analysis is included in the attached PDF.
        </p>
      </td>
    </tr>

    <!-- pdf badge -->
    <tr>
      <td style="padding:8px 24px 20px 24px;">
        <table cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="background:#eaf2f8;border:1px solid #d4e6f1;border-radius:8px;padding:12px 18px;">
            <span style="font-size:13px;color:#2980b9;font-family:{_FONT_STACK};">
              📎 PDF report attached
            </span>
          </td>
        </tr></table>
      </td>
    </tr>

    <!-- footer -->
    <tr>
      <td style="padding:20px 24px;border-top:1px solid #ecf0f1;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="font-size:12px;color:#95a5a6;font-family:{_FONT_STACK};">
              Regards,<br/>Supply Chain Monitor
            </td>
            <td align="right" style="font-size:11px;color:#bdc3c7;font-family:{_FONT_STACK};">
              Powered by <strong style="color:#00d2ff;">Supply Chain Monitor</strong>
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>

</td></tr>
</table>

</body>
</html>"""
        return html

    # -----------------------------------------------------------------------
    #  REPORT — plain-text builder (fallback)
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_report_plain(report_context: dict) -> str:
        company = report_context.get("company_name", "your company")
        period_start = report_context.get("period_start", "")
        period_end = report_context.get("period_end", "")
        incident_count = report_context.get("incident_count", 0)
        theme_count = report_context.get("theme_count", 0)
        escalation_rate = report_context.get("escalation_rate", 0)

        return (
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

    # ===================================================================
    #  PUBLIC API — send_alert
    # ===================================================================
    def send_alert(self, ctx: dict, needs_review: bool = False) -> None:
        msg = EmailMessage()

        initial_sev = (ctx.get("initial_severity") or "unknown").upper()
        final_sev = (ctx.get("severity") or initial_sev).upper()
        event_title = ctx.get("event_title") or (ctx.get("event_titles") or [""])[0] or "Supply-chain disruption"

        if needs_review:
            msg["Subject"] = (
                f"[{final_sev} — PENDING REVIEW] {event_title} — {ctx['company_name']}"
            )
        else:
            msg["Subject"] = f"[{final_sev}] {event_title} — {ctx['company_name']}"

        msg["From"] = SMTP_USER
        msg["To"] = ctx["contact_email"]

        # plain-text fallback first, then HTML alternative
        msg.set_content(self._build_alert_plain(ctx, needs_review))
        msg.add_alternative(self._build_alert_html(ctx, needs_review), subtype="html")

        self._send(msg)

    # ===================================================================
    #  PUBLIC API — send_report
    # ===================================================================
    def send_report(self, report_context: dict, pdf_path: str) -> None:
        msg = EmailMessage()
        company = report_context.get("company_name", "your company")
        period_start = report_context.get("period_start", "")
        period_end = report_context.get("period_end", "")
        contact_email = report_context["contact_email"]

        msg["Subject"] = f"Executive Supply Chain Report — {company} ({period_start} to {period_end})"
        msg["From"] = SMTP_USER
        msg["To"] = contact_email

        # plain-text fallback first, then HTML alternative
        msg.set_content(self._build_report_plain(report_context))
        msg.add_alternative(self._build_report_html(report_context), subtype="html")

        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        msg.add_attachment(pdf_data, maintype="application", subtype="pdf",
                           filename=f"report_{period_start}_{period_end}.pdf")

        self._send(msg)