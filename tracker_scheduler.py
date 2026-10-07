import time
import threading
import logging
from typing import Dict, Any, List, Optional

import tracker_db
from price_scraper import price_scraper
from email_service import email_service

logger = logging.getLogger("tracker_scheduler")

class PriceTrackingScheduler:
    def __init__(self):
        self._running = False
        self._thread = None
        self._interval_seconds = 300  # Default 5 minutes

    def start(self, interval_seconds: int = 300):
        if self._running:
            return
        self._interval_seconds = interval_seconds
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="PriceTrackerWorker")
        self._thread.start()
        logger.info(f"Price tracker background scheduler started (interval: {interval_seconds}s)")

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            try:
                # Dynamically respect user-configured interval if present
                settings = tracker_db.get_user_settings()
                raw_interval = settings.get("check_interval_minutes")
                if raw_interval:
                    try:
                        self._interval_seconds = max(60, int(raw_interval) * 60)
                    except ValueError:
                        pass

                self.check_all_active_products()
            except Exception as e:
                logger.error(f"Error in tracking scheduler loop: {e}")
            
            # Sleep in small increments for responsive shutdown
            for _ in range(self._interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def check_product_price(self, prod: Dict[str, Any]) -> Dict[str, Any]:
        """
        Checks a single product's URL, compares prices, evaluates percentage and
        minimum-amount alert rules, suppresses duplicates, and sends notifications.
        """
        prod_id = prod["id"]
        url = prod["product_url"]
        name = prod["product_name"]
        curr_price = float(prod.get("current_price") or 0.0)
        orig_price = float(prod.get("original_price") or curr_price)
        target_price = float(prod["target_price"]) if prod.get("target_price") is not None else None
        last_alert_price = float(prod["last_alert_price"]) if prod.get("last_alert_price") is not None else None
        currency = prod.get("currency") or "PKR"
        website = prod.get("website") or "Online Store"
        alert_threshold = float(prod["alert_threshold"]) if prod.get("alert_threshold") is not None else None
        user_email = prod.get("user_email")

        # 1. Fetch user-configured alert and notification settings
        settings = tracker_db.get_user_settings()
        price_drop_alerts_enabled = settings.get("price_drop_alerts_enabled", "true").lower() == "true"
        tracked_alerts_enabled = settings.get("tracked_alerts_enabled", "true").lower() == "true"
        email_notifications_enabled = settings.get("email_notifications_enabled", "true").lower() == "true"

        # Percentage threshold
        raw_pct = settings.get("price_drop_pct_threshold", "5")
        if str(raw_pct).lower() in ("any", "all", "0", ""):
            global_pct_threshold = 0.0
        else:
            try:
                global_pct_threshold = float(raw_pct)
            except ValueError:
                global_pct_threshold = 5.0

        active_pct_threshold = alert_threshold if alert_threshold is not None else global_pct_threshold

        # Minimum Price Drop Amount setting
        raw_min = settings.get("min_price_drop_amount")
        min_drop_amount = None
        if raw_min is not None and str(raw_min).strip() != "":
            try:
                val = float(raw_min)
                if val > 0:
                    min_drop_amount = val
            except ValueError:
                min_drop_amount = None

        recipient_email = user_email or settings.get("alert_email", "user@example.com")

        # 2. Scrape latest price from URL
        scraped = price_scraper.scrape_product_info(url)
        new_price = scraped.get("price")
        
        if new_price is None or new_price <= 0:
            unavailable_msg = "The tracked product is currently unavailable or could not be found."
            logger.warning(f"{unavailable_msg} for '{name}' at {url}")
            tracker_db.update_tracked_product(prod_id, tracking_status="unavailable")
            return {
                "product_id": prod_id,
                "product_name": name,
                "status": "unavailable",
                "message": unavailable_msg,
                "error": unavailable_msg,
                "alert_triggered": False,
                "trigger_reason": unavailable_msg
            }

        new_currency = scraped.get("currency") or currency

        # 3. Classify price movement
        is_price_drop = new_price < curr_price
        is_price_increase = new_price > curr_price
        is_price_equal = abs(new_price - curr_price) < 0.01

        drop_amount = max(0.0, curr_price - new_price)
        pct_drop = (drop_amount / curr_price * 100.0) if curr_price > 0 else 0.0

        ref_price = orig_price if orig_price > 0 else curr_price
        total_drop = max(0.0, ref_price - new_price)
        total_pct_drop = (total_drop / ref_price * 100.0) if ref_price > 0 else 0.0

        effective_pct = max(pct_drop, total_pct_drop)
        effective_drop = max(drop_amount, total_drop)

        # 4. Evaluate alert conditions
        alert_triggered = False
        trigger_reason = None

        if is_price_increase:
            trigger_reason = "Price increased"
        elif is_price_equal:
            if last_alert_price is not None and new_price >= (last_alert_price - 0.01):
                trigger_reason = "Duplicate alert suppressed"
            else:
                trigger_reason = "Price unchanged"
        elif not price_drop_alerts_enabled or not tracked_alerts_enabled:
            trigger_reason = "Alerts disabled in settings"
        else:
            condition_met = False

            # Condition A: Target price alert
            if target_price is not None and target_price > 0 and new_price <= target_price:
                condition_met = True
                trigger_reason = f"Price reached target (Current: {new_price} <= Target: {target_price})"

            # Condition B: Minimum Price Drop Amount setting (Section 5)
            # If the user sets Minimum Price Drop Amount >= product price (e.g. $1000 for a $1000 product),
            # this represents a ceiling/target threshold where any price decrease below it qualifies.
            # Do NOT require the price to decrease by the full product price!
            if not condition_met and min_drop_amount is not None:
                if min_drop_amount >= ref_price:
                    if new_price <= min_drop_amount:
                        condition_met = True
                        trigger_reason = f"Price dropped to {new_price} below ceiling ({min_drop_amount})"

            # Condition C: Percentage threshold
            if not condition_met:
                if active_pct_threshold is None or active_pct_threshold <= 0:
                    # "Any drop" mode
                    if min_drop_amount is not None and 0 < min_drop_amount < ref_price:
                        if effective_drop >= min_drop_amount:
                            condition_met = True
                            trigger_reason = f"Price dropped by {effective_drop:.2f} (>= min {min_drop_amount:.2f})"
                    else:
                        condition_met = True
                        trigger_reason = f"Price dropped from {curr_price} to {new_price}"
                else:
                    # Percentage threshold e.g. 5% (comparison uses >=)
                    if effective_pct >= active_pct_threshold:
                        if min_drop_amount is not None and 0 < min_drop_amount < ref_price:
                            if effective_drop >= min_drop_amount:
                                condition_met = True
                                trigger_reason = f"Price dropped by {effective_pct:.1f}% (>= threshold {active_pct_threshold}%) and drop {effective_drop:.2f} >= min {min_drop_amount:.2f}"
                        else:
                            condition_met = True
                            trigger_reason = f"Price dropped by {effective_pct:.1f}% (>= threshold {active_pct_threshold}%)"

            # 5. Deduplication check (Section 10)
            if condition_met:
                # Prevent duplicate alerts if already alerted at this price or if price hasn't dropped further
                if last_alert_price is not None and new_price >= (last_alert_price - 0.01):
                    logger.info(f"Skipping duplicate alert for '{name}': already alerted at price {last_alert_price} (current: {new_price})")
                    alert_triggered = False
                    trigger_reason = "Duplicate alert suppressed"
                else:
                    alert_triggered = True
            else:
                alert_triggered = False
                if not trigger_reason:
                    trigger_reason = f"Price drop ({effective_pct:.1f}%) below threshold ({active_pct_threshold}%)"

        # 6. Record updated price in DB
        updated_prod = tracker_db.record_price_update(prod_id, new_price, new_currency)

        # 7. Dispatch notifications if alert triggered
        email_result = None
        if alert_triggered:
            logger.info(f"ALERT TRIGGERED for '{name}': {trigger_reason}")
            if email_notifications_enabled:
                email_result = email_service.send_price_drop_alert(
                    product_id=prod_id,
                    product_name=name,
                    product_url=url,
                    current_price=new_price,
                    previous_price=curr_price,
                    currency=new_currency,
                    target_price=target_price,
                    recipient_email=recipient_email,
                    website=website,
                    drop_amount=drop_amount,
                    drop_percentage=pct_drop
                )
            else:
                tracker_db.record_alert_sent(
                    prod_id=prod_id,
                    price=new_price,
                    alert_type="price_drop",
                    recipient_email=recipient_email,
                    subject=f"Price Drop Alert — {name}",
                    body=f"Price dropped from {curr_price} to {new_price}",
                    previous_price=curr_price,
                    drop_amount=drop_amount,
                    drop_percentage=pct_drop
                )

        return {
            "product_id": prod_id,
            "product_name": name,
            "previous_price": curr_price,
            "new_price": new_price,
            "drop_amount": drop_amount if is_price_drop else 0.0,
            "drop_percentage": pct_drop if is_price_drop else 0.0,
            "currency": new_currency,
            "target_price": target_price,
            "alert_triggered": alert_triggered,
            "trigger_reason": trigger_reason,
            "email_result": email_result
        }

    def check_all_active_products(self) -> List[Dict[str, Any]]:
        products = tracker_db.get_all_tracked_products()
        results = []
        for prod in products:
            if prod.get("tracking_status") != "paused":
                res = self.check_product_price(prod)
                results.append(res)
        return results

    check_all_tracked_products = check_all_active_products

tracker_scheduler = PriceTrackingScheduler()
