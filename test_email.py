"""
Quick smoke test for email delivery.
Sends a test alert email and a test report email (without PDF attachment)
to verify SMTP credentials and email_delivery.py work correctly.
"""
import os
import sys
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

def test_smtp_connection():
    """Step 1: Test raw SMTP connection + auth."""
    print("=" * 60)
    print("STEP 1: Testing SMTP connection to smtp.gmail.com:587")
    print("=" * 60)

    if not SMTP_USER or not SMTP_APP_PASSWORD:
        print("  [FAIL] SMTP_USER or SMTP_APP_PASSWORD not set in .env")
        return False

    print(f"  SMTP_USER        = {SMTP_USER}")
    print(f"  SMTP_APP_PASSWORD= {'*' * (len(SMTP_APP_PASSWORD) - 4) + SMTP_APP_PASSWORD[-4:]}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            print("  [OK] EHLO succeeded")
            server.starttls()
            print("  [OK] STARTTLS succeeded")
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            print("  [OK] LOGIN succeeded -- credentials are valid")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"  [FAIL] Authentication failed: {e}")
        print("    -> Check your SMTP_APP_PASSWORD (must be a Gmail App Password, not your login password)")
        return False
    except Exception as e:
        print(f"  [FAIL] Connection/TLS error: {e}")
        return False


def test_send_alert_email():
    """Step 2: Send a test alert email using EmailDelivery.send_alert()."""
    print()
    print("=" * 60)
    print("STEP 2: Sending test alert email via EmailDelivery.send_alert()")
    print("=" * 60)

    try:
        from phase2.phase7.delivery.email_delivery import EmailDelivery
        print("  [OK] EmailDelivery imported successfully")
    except Exception as e:
        print(f"  [FAIL] Import failed: {e}")
        return False

    delivery = EmailDelivery()

    # Construct a realistic test context
    ctx = {
        "assessment_id": "test_assessment_001",
        "customer_id": "cust_apex_001",
        "supplier_id": "supp_apex_tsmc",
        "initial_severity": "HIGH",
        "severity": "CRITICAL",
        "company_name": "Apex Electronics Inc.",
        "contact_email": SMTP_USER,  # send to ourselves for testing
        "confidence": 0.87,
        "predicted_business_impact": (
            "Potential 2-week delay in AX1 Application Processor delivery. "
            "Estimated revenue impact: $450M if unmitigated."
        ),
        "evidence": [
            "TSMC Fab 18 reported partial shutdown due to magnitude 6.1 earthquake in Hsinchu",
            "Historical data: similar event in 2022 caused 12-day production halt",
            "Current inventory buffer: 14 days (marginal)",
        ],
        "recommended_actions_json": '[{"urgency":"immediate","action":"Activate safety stock allocation for AX1 processor","rationale":"14-day buffer may not cover extended shutdown"},{"urgency":"24h","action":"Contact Samsung foundry for emergency 5nm capacity","rationale":"Backup fab qualification completed Q1 2026"}]',
        "affected_product_ids": ["prod_apex_phone", "prod_apex_laptop"],
        "updated_at": "2026-07-16T21:30:00+05:30",
        "event_title": "Earthquake near TSMC Hsinchu facility",
        "event_titles": ["Earthquake near TSMC Hsinchu facility"],
    }

    try:
        delivery.send_alert(ctx, needs_review=False)
        print(f"  [OK] Alert email sent to {ctx['contact_email']}")
        return True
    except Exception as e:
        print(f"  [FAIL] send_alert() failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_send_raw_email():
    """Step 3: Send a minimal raw test email (bypasses EmailDelivery)."""
    print()
    print("=" * 60)
    print("STEP 3: Sending a minimal raw test email")
    print("=" * 60)

    msg = EmailMessage()
    msg["Subject"] = "[TEST] Supply Chain Monitor -- Email Connectivity Check"
    msg["From"] = SMTP_USER
    msg["To"] = SMTP_USER
    msg.set_content(
        "This is a test email from the Supply Chain Monitor platform.\n\n"
        "If you received this, email delivery is working correctly.\n\n"
        "-- Supply Chain Monitor Test Suite"
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.send_message(msg)
        print(f"  [OK] Raw test email sent to {SMTP_USER}")
        return True
    except Exception as e:
        print(f"  [FAIL] Failed: {e}")
        return False


if __name__ == "__main__":
    results = {}

    results["smtp_connection"] = test_smtp_connection()

    if results["smtp_connection"]:
        results["raw_email"] = test_send_raw_email()
        results["alert_email"] = test_send_alert_email()
    else:
        print("\n[WARN] Skipping email send tests -- SMTP connection failed")
        results["raw_email"] = False
        results["alert_email"] = False

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}  {test_name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("All email tests passed! Email delivery is working correctly.")
    else:
        print("[WARN] Some tests failed -- check output above for details.")

    sys.exit(0 if all_pass else 1)
