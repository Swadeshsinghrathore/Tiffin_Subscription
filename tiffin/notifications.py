"""
TiffinBox Notification Service
Handles daily 9:00 AM customer delivery notifications, email rendering,
and dispatch logging.
"""

from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import smtplib
from typing import Optional

from tiffin.billing import status_on
from tiffin.models import Customer, Status
from tiffin.repository import (
    create_notification_log,
    get_customers,
    get_holiday_dates,
    get_pauses_for_customer,
)

logger = logging.getLogger(__name__)


def is_delivery_weekday(d: date) -> bool:
    """Return True if Monday through Friday."""
    return d.weekday() < 5


def get_customers_due_delivery_today(
    on_date: Optional[date] = None,
) -> tuple[bool, str, list[Customer]]:
    """
    Determine which customers are due for lunch delivery on the given date.
    
    Rules:
    1. Must be a delivery weekday (Mon–Fri).
    2. Must NOT be a kitchen holiday closure.
    3. Customer must be actively subscribed (start_date <= on_date <= end_date).
    4. Customer must NOT be paused on that date.
    
    Returns:
        (is_delivery_day, reason_message, list_of_active_customers)
    """
    check_date = on_date or date.today()

    # Rule 1: Mon–Fri only
    if not is_delivery_weekday(check_date):
        day_name = check_date.strftime("%A")
        return (
            False,
            f"{day_name} is a weekend. Tiffin deliveries run Monday through Friday only.",
            [],
        )

    # Rule 2: Exclude kitchen holidays
    holidays = get_holiday_dates()
    if check_date in holidays:
        date_str = check_date.strftime("%b %d, %Y")
        return (
            False,
            f"Kitchen service is closed today ({date_str}) for scheduled service holiday.",
            [],
        )

    # Rules 3 & 4: Subscribed and not paused
    all_customers = get_customers()
    eligible: list[Customer] = []

    for cust in all_customers:
        pauses = get_pauses_for_customer(cust.id)  # type: ignore
        status = status_on(cust, pauses, check_date)
        if status == Status.ACTIVE:
            eligible.append(cust)

    return (
        True,
        f"Delivery scheduled for {len(eligible)} active subscribers.",
        eligible,
    )


def build_delivery_notification_email(
    customer: Customer,
    delivery_date: date,
    portal_url: str = "http://127.0.0.1:5000/customer/login",
) -> tuple[str, str, str]:
    """
    Construct email subject, plain text body, and responsive HTML body.
    """
    plan_name = customer.plan.name if customer.plan else "Standard Lunch"
    date_formatted = delivery_date.strftime("%A, %B %d, %Y")
    subject = f"🍱 Lunch Delivery Today: Your {plan_name} is on the way!"

    text_body = f"""Hello {customer.name},

Good morning! Your daily lunch is freshly prepared and scheduled for delivery today:

- Meal Plan: {plan_name}
- Delivery Date: {date_formatted}
- Expected Window: 12:00 PM – 1:30 PM
- Destination: {customer.address or 'Registered Delivery Address'}

Going out of town or fasting next week?
Pause deliveries anytime from your customer portal:
{portal_url}

Thank you,
Annapurna Tiffin Kitchen
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F9FAFB; margin: 0; padding: 24px; }}
    .email-container {{ max-width: 560px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; overflow: hidden; }}
    .header {{ background: #0F172A; color: #FFFFFF; padding: 20px 24px; display: flex; align-items: center; justify-content: space-between; }}
    .header h2 {{ margin: 0; font-size: 18px; }}
    .content {{ padding: 24px; color: #334155; line-height: 1.6; font-size: 14px; }}
    .delivery-box {{ background: #FFF7ED; border: 1px solid #FFEDD5; border-radius: 6px; padding: 16px; margin: 16px 0; }}
    .meta-row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }}
    .cta-btn {{ display: inline-block; background: #EA580C; color: #FFFFFF !important; text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; font-size: 13px; margin-top: 14px; }}
    .footer {{ background: #F8FAFC; padding: 16px 24px; border-top: 1px solid #E5E7EB; font-size: 12px; color: #64748B; }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <div>
        <h2>🍱 TiffinBox Notification</h2>
        <span style="font-size: 12px; color: #94A3B8;">Annapurna Home Tiffin Service</span>
      </div>
      <span style="font-size: 12px; background: #16A34A; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 600;">Due Today</span>
    </div>

    <div class="content">
      <p style="margin-top: 0;">Good morning <strong>{customer.name}</strong>,</p>
      <p>Your lunch for <strong>{date_formatted}</strong> is freshly prepared and out for delivery.</p>

      <div class="delivery-box">
        <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #C2410C; margin-bottom: 8px; letter-spacing: 0.05em;">Today's Delivery Details</div>
        <div class="meta-row">
          <span>Meal Plan:</span>
          <strong>{plan_name}</strong>
        </div>
        <div class="meta-row">
          <span>Expected Window:</span>
          <strong>12:00 PM &ndash; 1:30 PM</strong>
        </div>
        <div class="meta-row">
          <span>Delivery Address:</span>
          <span>{customer.address or 'Standard Delivery Address'}</span>
        </div>
        <div class="meta-row">
          <span>Contact Key:</span>
          <code style="color: #0F172A; font-weight: 600;">{customer.phone}</code>
        </div>
      </div>

      <p style="font-size: 13px; color: #64748B;">
        Need to pause for an upcoming trip or festival? Remember: weekend pauses are never charged, and billing is pro-rated automatically.
      </p>

      <a href="{portal_url}" class="cta-btn">
        Open Customer Portal &rarr;
      </a>
    </div>

    <div class="footer">
      Mon&ndash;Fri Lunch Delivery &bull; Exact Integer Paise Pro-Rata &bull; Pure Date-Set Operations
    </div>
  </div>
</body>
</html>
"""
    return subject, text_body, html_body


def _load_dotenv_if_present() -> None:
    """Load key-value pairs from .env if present and not already in os.environ."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for env_path in candidates:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception as e:
                logger.warning("Could not read .env file: %s", e)
            break


def send_delivery_email(
    customer: Customer,
    delivery_date: date,
    portal_url: str = "http://127.0.0.1:5000/customer/login",
) -> tuple[bool, str]:
    """
    Send delivery email to a single customer.
    If SMTP host is configured, attempts real dispatch.
    Otherwise records a valid logged notification in notification_logs.
    """
    _load_dotenv_if_present()

    recipient_email = customer.email
    if not recipient_email or not recipient_email.strip():
        # Fallback email based on customer phone
        recipient_email = f"customer_{customer.phone}@tiffinbox.local"

    subject, text_content, html_content = build_delivery_notification_email(
        customer, delivery_date, portal_url
    )

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    if smtp_pass:
        smtp_pass = smtp_pass.replace(" ", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", f"TiffinBox Notifications <{smtp_user or 'notifications@tiffinbox.com'}>")
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() in ("true", "1", "yes") or smtp_port == 465

    if smtp_host:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = recipient_email
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_from, [recipient_email], msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    if os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"):
                        server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_from, [recipient_email], msg.as_string())

            create_notification_log(
                customer_id=customer.id,  # type: ignore
                recipient_email=recipient_email,
                subject=subject,
                delivery_date=delivery_date,
                status="sent",
                details=f"Dispatched via SMTP server {smtp_host}:{smtp_port}",
            )
            return True, f"Sent to {recipient_email} via SMTP"

        except Exception as e:
            logger.exception("SMTP send error for customer %s", customer.phone)
            create_notification_log(
                customer_id=customer.id,  # type: ignore
                recipient_email=recipient_email,
                subject=subject,
                delivery_date=delivery_date,
                status="failed",
                details=f"SMTP send failed: {e}",
            )
            return False, f"SMTP Error: {e}"

    # Local development / Demo mode: Safely record as logged notification
    create_notification_log(
        customer_id=customer.id,  # type: ignore
        recipient_email=recipient_email,
        subject=subject,
        delivery_date=delivery_date,
        status="logged",
        details="Simulated notification logged (SMTP server not configured). Delivery details saved.",
    )
    return True, f"Logged notification for {recipient_email}"


def dispatch_daily_delivery_notifications(
    on_date: Optional[date] = None,
    portal_url: str = "http://127.0.0.1:5000/customer/login",
) -> dict:
    """
    Main dispatch engine called at 9:00 AM daily or by the owner on demand.
    Identifies all eligible customers for the date and sends notifications.
    """
    check_date = on_date or date.today()
    is_delivery, reason, eligible_customers = get_customers_due_delivery_today(check_date)

    if not is_delivery:
        return {
            "success": True,
            "delivery_day": False,
            "date": check_date.isoformat(),
            "reason": reason,
            "total_eligible": 0,
            "sent_count": 0,
            "failed_count": 0,
            "customers": [],
        }

    sent = 0
    failed = 0
    customer_names = []

    for cust in eligible_customers:
        ok, msg = send_delivery_email(cust, check_date, portal_url)
        if ok:
            sent += 1
            customer_names.append(cust.name)
        else:
            failed += 1

    return {
        "success": True,
        "delivery_day": True,
        "date": check_date.isoformat(),
        "reason": f"Dispatched 9:00 AM delivery notifications for {sent} active subscribers.",
        "total_eligible": len(eligible_customers),
        "sent_count": sent,
        "failed_count": failed,
        "customers": customer_names,
    }
