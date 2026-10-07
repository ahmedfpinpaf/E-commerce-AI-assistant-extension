import os
import smtplib
import logging
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

import tracker_db

logger = logging.getLogger("email_service")

class EmailAlertService:
    def __init__(self):
        # Support both SMTP_HOST and SMTP_SERVER from environment
        self.smtp_host = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", os.getenv("SMTP_USER") or "alerts@shopai-assistant.com")

    def send_price_drop_alert(
        self,
        product_id: str,
        product_name: str,
        product_url: str,
        current_price: float,
        previous_price: float,
        currency: str = "PKR",
        target_price: Optional[float] = None,
        recipient_email: Optional[str] = None,
        website: Optional[str] = None,
        drop_amount: Optional[float] = None,
        drop_percentage: Optional[float] = None,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Sends price-drop email notification compliant with Section 8 specification:
        
        Price Drop Alert!
        
        Product: [Product Name]
        Previous Price: [Currency] [Previous Price]
        Current Price: [Currency] [Current Price]
        Price Drop: [Currency] [Price Drop]
        Drop Percentage: [Percentage]%
        Website: [Website]
        Time of Price Drop: [Time]
        
        View Product:
        [Product URL]
        """
        if not recipient_email:
            settings = tracker_db.get_user_settings()
            recipient_email = settings.get("alert_email", "user@example.com")

        # Calculate drops if not provided
        if drop_amount is None:
            drop_amount = max(0.0, previous_price - current_price)
        if drop_percentage is None:
            drop_percentage = (drop_amount / previous_price * 100.0) if previous_price > 0 else 0.0

        ts = timestamp or time.time()
        time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")
        store_website = website or "Online Store"

        subject = f"Price Drop Alert! — {product_name}"
        
        curr_str = f"{currency} {current_price:,.0f}" if current_price.is_integer() else f"{currency} {current_price:,.2f}"
        prev_str = f"{currency} {previous_price:,.0f}" if previous_price.is_integer() else f"{currency} {previous_price:,.2f}"
        drop_str = f"{currency} {drop_amount:,.0f}" if drop_amount.is_integer() else f"{currency} {drop_amount:,.2f}"
        pct_str = f"{drop_percentage:.1f}%" if drop_percentage % 1 != 0 else f"{drop_percentage:.0f}%"

        body_text = (
            f"Price Drop Alert!\n\n"
            f"Product: {product_name}\n"
            f"Previous Price: {prev_str}\n"
            f"Current Price: {curr_str}\n"
            f"Price Drop: {drop_str}\n"
            f"Drop Percentage: {pct_str}\n"
            f"Website: {store_website}\n"
            f"Time of Price Drop: {time_str}\n"
        )

        if target_price:
            targ_str = f"{currency} {target_price:,.0f}" if target_price.is_integer() else f"{currency} {target_price:,.2f}"
            body_text += f"Target Alert Price: {targ_str}\n"

        body_text += (
            f"\nView Product:\n"
            f"{product_url}\n"
        )

        sent_via = "logged"
        error_msg = None

        # Attempt SMTP delivery if credentials configured
        if self.smtp_host and self.smtp_user and self.smtp_pass:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = self.smtp_from
                msg["To"] = recipient_email
                msg.attach(MIMEText(body_text, "plain"))
                
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(self.smtp_from, [recipient_email], msg.as_string())
                sent_via = "smtp"
                logger.info(f"Price drop email successfully dispatched to {recipient_email} via SMTP")
            except Exception as e:
                logger.warning(f"SMTP send failed: {e}. Falling back to internal alert log.")
                error_msg = str(e)
                sent_via = "failed_smtp_logged"

        # Record alert in DB
        tracker_db.record_alert_sent(
            prod_id=product_id,
            price=current_price,
            alert_type="price_drop" if not target_price or current_price > target_price else "target_reached",
            recipient_email=recipient_email,
            subject=subject,
            body=body_text,
            previous_price=previous_price,
            drop_amount=drop_amount,
            drop_percentage=drop_percentage
        )

        return {
            "success": True,
            "mode": sent_via,
            "recipient": recipient_email,
            "subject": subject,
            "body": body_text,
            "drop_amount": drop_amount,
            "drop_percentage": drop_percentage,
            "error": error_msg
        }

email_service = EmailAlertService()
