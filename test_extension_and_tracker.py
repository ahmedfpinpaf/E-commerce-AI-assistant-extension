"""
Test Suite for Chrome Extension Backend & Product Price Tracker
Covers:
1. Product price scraper and metadata extractor across Daraz, Amazon, OLX, eBay fixtures.
2. SQLite tracker database: tracked products, price history, user settings, alert logs.
3. Scheduler & alert triggers: target price alert, general price drop, alert deduplication.
4. FastAPI tracking REST API endpoints:
   - GET /api/tracked-products
   - POST /api/track-product
   - GET /api/tracked-products/{id}
   - PATCH /api/tracked-products/{id}
   - DELETE /api/tracked-products/{id}
   - GET /api/tracked-products/{id}/history
   - POST /api/check-price/{id}
   - POST /api/check-all-prices
   - GET /api/settings & POST /api/settings
   - POST /api/test-email-alert
   - GET /api/alert-logs
   - GET /test_pages/{filename}
5. Extension NLP Chatbot endpoint (/api/extension/chat):
   - "What is this product?"
   - "Track this product"
   - "Alert me when it falls below PKR 160,000"
   - "Show tracked products"
   - "Stop tracking"
"""

import json
import os
import sys
import unittest
from fastapi.testclient import TestClient

from app import app
import tracker_db
from price_scraper import price_scraper, ProductPriceScraper
from tracker_scheduler import tracker_scheduler
from email_service import email_service

client = TestClient(app)

class TestProductPriceScraper(unittest.TestCase):
    def test_daraz_extraction(self):
        with open("test_pages/daraz_samsung_s24.html", "r", encoding="utf-8") as f:
            html = f.read()
        data = price_scraper.extract_from_html(html, "https://www.daraz.pk/products/samsung-galaxy-s24.html")
        self.assertEqual(data["website"], "Daraz")
        self.assertEqual(data["name"], "Samsung Galaxy S24")
        self.assertEqual(data["brand"], "Samsung")
        self.assertEqual(data["model"], "Galaxy S24")
        self.assertEqual(data["price"], 180000.0)
        self.assertEqual(data["currency"], "PKR")

    def test_amazon_extraction(self):
        with open("test_pages/amazon_dell_xps.html", "r", encoding="utf-8") as f:
            html = f.read()
        data = price_scraper.extract_from_html(html, "https://www.amazon.com/dp/B0CX2TEST")
        self.assertEqual(data["website"], "Amazon")
        self.assertIn("Dell XPS 13", data["name"])
        self.assertEqual(data["brand"], "Dell")
        self.assertEqual(data["price"], 999.0)
        self.assertEqual(data["currency"], "USD")

    def test_olx_extraction(self):
        with open("test_pages/olx_iphone.html", "r", encoding="utf-8") as f:
            html = f.read()
        data = price_scraper.extract_from_html(html, "https://www.olx.com.pk/item/iphone-15-pro-max-iid-10928374")
        self.assertEqual(data["website"], "OLX")
        self.assertIn("iPhone 15 Pro Max", data["name"])
        self.assertEqual(data["price"], 340000.0)
        self.assertEqual(data["currency"], "PKR")

    def test_ebay_extraction(self):
        with open("test_pages/ebay_laptop.html", "r", encoding="utf-8") as f:
            html = f.read()
        data = price_scraper.extract_from_html(html, "https://www.ebay.com/itm/195829104812")
        self.assertEqual(data["website"], "eBay")
        self.assertIn("Lenovo ThinkPad", data["name"])
        self.assertEqual(data["price"], 650.0)
        self.assertEqual(data["currency"], "USD")


class TestTrackerDatabaseAndScheduler(unittest.TestCase):
    def setUp(self):
        # Clear simulation registry before each test
        price_scraper.clear_simulated_prices()

    def test_db_lifecycle_and_history(self):
        test_url = "https://www.daraz.pk/products/unit-test-phone-999.html"
        
        # 1. Add product
        prod = tracker_db.add_tracked_product(
            product_name="Unit Test Phone",
            product_url=test_url,
            website="Daraz",
            current_price=50000.0,
            currency="PKR",
            brand="TestBrand",
            target_price=45000.0
        )
        prod_id = prod["id"]
        self.assertIsNotNone(prod_id)
        self.assertEqual(prod["current_price"], 50000.0)
        self.assertEqual(prod["target_price"], 45000.0)

        # 2. Record price update
        updated = tracker_db.record_price_update(prod_id, 47000.0, "PKR")
        self.assertEqual(updated["current_price"], 47000.0)
        self.assertEqual(updated["previous_price"], 50000.0)

        # 3. Check price history
        history = tracker_db.get_price_history(prod_id)
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[0]["price"], 50000.0)
        self.assertEqual(history[1]["price"], 47000.0)

        # 4. Settings update and retrieval
        tracker_db.update_user_settings({"alert_email": "ma0819262@gmail.com"})
        settings = tracker_db.get_user_settings()
        self.assertEqual(settings.get("alert_email"), "ma0819262@gmail.com")

        # 5. Clean up
        tracker_db.delete_tracked_product(prod_id)
        self.assertIsNone(tracker_db.get_tracked_product(prod_id))

    def test_alert_trigger_and_deduplication(self):
        test_url = "https://www.daraz.pk/products/alert-test-item-888.html"
        
        prod = tracker_db.add_tracked_product(
            product_name="Alert Test S24",
            product_url=test_url,
            website="Daraz",
            current_price=180000.0,
            currency="PKR",
            target_price=160000.0,
            alert_type="target_price"
        )
        prod_id = prod["id"]

        # Simulate price dropping to 155,000 (below 160,000 target)
        price_scraper.set_simulated_price(test_url, 155000.0, "PKR")
        
        # Check price - should trigger alert
        check_result_1 = tracker_scheduler.check_product_price(prod)
        self.assertTrue(check_result_1["alert_triggered"])
        self.assertEqual(check_result_1["new_price"], 155000.0)

        # Check DB that last_alert_price was updated
        refreshed_prod = tracker_db.get_tracked_product(prod_id)
        self.assertEqual(refreshed_prod["last_alert_price"], 155000.0)
        self.assertEqual(refreshed_prod["tracking_status"], "alert_triggered")

        # Check alert logs table
        logs = tracker_db.get_alert_logs()
        self.assertTrue(any(l["product_id"] == prod_id for l in logs))

        # Check deduplication: run check_product_price again with same price 155,000
        check_result_2 = tracker_scheduler.check_product_price(refreshed_prod)
        self.assertFalse(check_result_2["alert_triggered"], "Duplicate alert must be suppressed")
        self.assertEqual(check_result_2["trigger_reason"], "Duplicate alert suppressed")

        # Clean up
        tracker_db.delete_tracked_product(prod_id)
        price_scraper.clear_simulated_prices()


class TestFastAPIEndpoints(unittest.TestCase):
    def test_test_pages_served(self):
        resp = client.get("/test_pages/daraz_samsung_s24.html")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Samsung Galaxy S24", resp.text)

    def test_track_product_api_crud(self):
        # 1. Add product via API
        payload = {
            "product_name": "API Test Laptop",
            "product_url": "https://www.amazon.com/dp/B0TESTLAPTOP",
            "website": "Amazon",
            "current_price": 1200.0,
            "currency": "USD",
            "brand": "Dell",
            "target_price": 1100.0,
            "alert_type": "target_price"
        }
        res = client.post("/api/track-product", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        prod_id = data["id"]
        self.assertEqual(data["product_name"], "API Test Laptop")

        # 2. Get single product
        get_res = client.get(f"/api/tracked-products/{prod_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["id"], prod_id)

        # 3. Patch product (update target price and pause)
        patch_res = client.patch(f"/api/tracked-products/{prod_id}", json={
            "target_price": 1050.0,
            "tracking_status": "paused"
        })
        self.assertEqual(patch_res.status_code, 200)
        patched = patch_res.json()
        self.assertEqual(patched["target_price"], 1050.0)
        self.assertEqual(patched["tracking_status"], "paused")

        # 4. Check price history endpoint
        hist_res = client.get(f"/api/tracked-products/{prod_id}/history")
        self.assertEqual(hist_res.status_code, 200)
        self.assertIsInstance(hist_res.json(), list)

        # 5. Delete product
        del_res = client.delete(f"/api/tracked-products/{prod_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["success"])

    def test_settings_api(self):
        post_res = client.post("/api/settings", json={
            "alert_email": "api_test@example.com",
            "check_interval_minutes": "10",
            "notifications_enabled": "true"
        })
        self.assertEqual(post_res.status_code, 200)
        
        get_res = client.get("/api/settings")
        self.assertEqual(get_res.status_code, 200)
        settings = get_res.json()
        self.assertEqual(settings.get("alert_email"), "api_test@example.com")
        self.assertEqual(settings.get("check_interval_minutes"), "10")

    def test_email_test_alert_endpoint(self):
        res = client.post("/api/test-email-alert")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("Price Drop Alert", data.get("subject"))

    def test_extension_chat_commands(self):
        active_prod = {
            "name": "Samsung Galaxy S24 Ultra",
            "brand": "Samsung",
            "model": "S24 Ultra",
            "price": 380000.0,
            "currency": "PKR",
            "url": "https://www.daraz.pk/products/samsung-s24-ultra.html",
            "website": "Daraz"
        }

        # Query 1: "What is this product?"
        resp1 = client.post("/api/extension/chat", json={
            "message": "What is this product?",
            "active_product": active_prod
        })
        self.assertEqual(resp1.status_code, 200)
        reply1 = resp1.json()["reply"]
        self.assertIn("Samsung Galaxy S24 Ultra", reply1)
        self.assertIn("PKR 380,000", reply1)

        # Query 2: "Track this product and alert me when it falls below PKR 350,000"
        resp2 = client.post("/api/extension/chat", json={
            "message": "Track this product and alert me when it falls below PKR 350,000",
            "active_product": active_prod
        })
        self.assertEqual(resp2.status_code, 200)
        res2_json = resp2.json()
        self.assertTrue(res2_json["tracked_product_added"])
        self.assertIn("Tracking Started", res2_json["reply"])
        self.assertIn("350,000", res2_json["reply"])

        # Query 3: "Show tracked products"
        resp3 = client.post("/api/extension/chat", json={
            "message": "Show tracked products",
            "active_product": active_prod
        })
        self.assertEqual(resp3.status_code, 200)
        reply3 = resp3.json()["reply"]
        self.assertIn("Samsung Galaxy S24 Ultra", reply3)

        # Query 4: "Stop tracking"
        resp4 = client.post("/api/extension/chat", json={
            "message": "Stop tracking",
            "active_product": active_prod
        })
        self.assertEqual(resp4.status_code, 200)
        reply4 = resp4.json()["reply"]
        self.assertIn("Stopped tracking", reply4)


class TestChromeExtensionPackage(unittest.TestCase):
    def test_manifest_v3_structure(self):
        import json
        manifest_path = os.path.join("chrome-extension", "manifest.json")
        self.assertTrue(os.path.exists(manifest_path), "manifest.json must exist in chrome-extension directory")
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest.get("manifest_version"), 3, "Manifest must be V3")
        self.assertIn("ShopAI", manifest.get("name", ""))
        self.assertIn("activeTab", manifest.get("permissions", []))
        self.assertIn("storage", manifest.get("permissions", []))
        self.assertIn("http://localhost:8000/*", manifest.get("host_permissions", []))
        
        # Verify background worker
        bg = manifest.get("background", {}).get("service_worker")
        self.assertIsNotNone(bg)
        self.assertTrue(os.path.exists(os.path.join("chrome-extension", bg)))

        # Verify action popup
        popup = manifest.get("action", {}).get("default_popup")
        self.assertIsNotNone(popup)
        self.assertTrue(os.path.exists(os.path.join("chrome-extension", popup)))

        # Verify content scripts
        content_scripts = manifest.get("content_scripts", [])
        self.assertGreaterEqual(len(content_scripts), 1)
        for cs in content_scripts:
            for js in cs.get("js", []):
                self.assertTrue(os.path.exists(os.path.join("chrome-extension", js)), f"{js} must exist")
            for css in cs.get("css", []):
                self.assertTrue(os.path.exists(os.path.join("chrome-extension", css)), f"{css} must exist")

    def test_extension_icons_and_files(self):
        import struct
        icon_sizes = [16, 48, 128]
        for size in icon_sizes:
            icon_path = os.path.join("chrome-extension", "icons", f"icon{size}.png")
            self.assertTrue(os.path.exists(icon_path), f"icon{size}.png must exist")
            with open(icon_path, "rb") as f:
                header = f.read(8)
                self.assertEqual(header, b'\x89PNG\r\n\x1a\n', f"icon{size}.png must be a valid PNG")
                # Read IHDR chunk
                length_bytes = f.read(4)
                chunk_type = f.read(4)
                self.assertEqual(chunk_type, b'IHDR')
                w, h = struct.unpack(">II", f.read(8))
                self.assertEqual(w, size)
                self.assertEqual(h, size)

    def test_popup_and_content_files(self):
        required_files = [
            "popup.html",
            "popup.css",
            "popup.js",
            "content.js",
            "content.css",
            "background.js",
            "options.html",
            "options.css",
            "options.js"
        ]
        for filename in required_files:
            file_path = os.path.join("chrome-extension", filename)
            self.assertTrue(os.path.exists(file_path), f"{filename} must exist")
            self.assertGreater(os.path.getsize(file_path), 500, f"{filename} must not be empty")

    def test_settings_page_has_no_chat_and_only_alerts_and_notifications(self):
        from bs4 import BeautifulSoup

        # 1. Verify in popup.html (#panel-settings)
        with open("chrome-extension/popup.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        settings_panel = soup.find("section", {"id": "panel-settings"})
        self.assertIsNotNone(settings_panel, "Settings section #panel-settings must exist in popup.html")
        settings_html = str(settings_panel).lower()

        # Must NOT contain chat-related components
        self.assertNotIn("chat-messages", settings_html)
        self.assertNotIn("chat-input", settings_html)
        self.assertNotIn("btn-chat-send", settings_html)
        self.assertNotIn("chat-bubble", settings_html)
        self.assertNotIn("llm", settings_html)
        self.assertNotIn("recommend a", settings_html)

        # Must contain Alert Settings
        self.assertIn("alert settings", settings_html)
        self.assertIn("price drop alerts", settings_html)
        self.assertIn("tracked products alerts", settings_html)
        self.assertIn("minimum price drop", settings_html)
        self.assertIn("alert frequency", settings_html)

        # Must contain Notification Settings
        self.assertIn("notification settings", settings_html)
        self.assertIn("browser notifications", settings_html)
        self.assertIn("email notifications", settings_html)
        self.assertIn("email address", settings_html)
        self.assertIn("save settings", settings_html)

        # 2. Verify in options.html
        with open("chrome-extension/options.html", "r", encoding="utf-8") as f:
            opt_html = f.read().lower()

        self.assertNotIn("chat-messages", opt_html)
        self.assertNotIn("chat-input", opt_html)
        self.assertNotIn("btn-chat-send", opt_html)
        self.assertIn("alert settings", opt_html)
        self.assertIn("notification settings", opt_html)

    def test_main_assistant_retains_chatbot_and_tracking(self):
        with open("chrome-extension/popup.html", "r", encoding="utf-8") as f:
            html = f.read()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        assistant_panel = soup.find("section", {"id": "panel-assistant"})
        self.assertIsNotNone(assistant_panel, "#panel-assistant must exist")

        # Must retain product tracking
        self.assertIsNotNone(assistant_panel.find(id="btn-track-product"))
        self.assertIsNotNone(assistant_panel.find(id="product-card"))

        # Must retain chatbot UI in Assistant tab
        self.assertIsNotNone(assistant_panel.find(id="chat-messages"))
        self.assertIsNotNone(assistant_panel.find(id="chat-input"))
        self.assertIsNotNone(assistant_panel.find(id="btn-chat-send"))



class TestPriceTrackingAndAlertScenarios(unittest.TestCase):
    """
    Mandatory verification scenarios from Section 15 & System Specifications:
    1. Test 1: Price remains the same ($1000 -> $1000) -> No alert
    2. Test 2: Small price drop ($1000 -> $990, threshold 5%) -> No alert
    3. Test 3: Threshold reached ($1000 -> $950, threshold 5%) -> Send alert
    4. Test 4: Threshold exceeded ($1000 -> $900, threshold 5%) -> Send alert
    5. Test 5: Price increases ($950 -> $1000) -> No alert (only price update)
    6. Test 6: Min drop amount setting ($1000 price, $1000 min drop setting, $999 new) -> Alert triggered
    7. Test 7: Exact product tracking (only tracks requested product URL)
    8. Test 8: Email notification required fields (Section 8)
    9. Test 9: Database stored product state fields (Section 3)
    10. Test 10: Duplicate alert suppression on consecutive identical prices
    """

    def setUp(self):
        price_scraper.clear_simulated_prices()
        tracker_db.update_user_settings({
            "price_drop_alerts_enabled": "true",
            "tracked_alerts_enabled": "true",
            "email_notifications_enabled": "true",
            "price_drop_pct_threshold": "5",
            "min_price_drop_amount": "0",
            "alert_email": "test_alerts@example.com"
        })
        with tracker_db.get_db_connection() as conn:
            conn.execute("DELETE FROM tracked_products WHERE product_url LIKE '%scenario-test%'")
            conn.commit()

    def tearDown(self):
        price_scraper.clear_simulated_prices()
        with tracker_db.get_db_connection() as conn:
            conn.execute("DELETE FROM tracked_products WHERE product_url LIKE '%scenario-test%'")
            conn.commit()

    def test_scenario_1_no_price_change(self):
        """Test 1: Old: $1000, New: $1000 -> Result: No alert"""
        url = "https://www.example.com/scenario-test-item-1"
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 1",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0
        )
        price_scraper.set_simulated_price(url, 1000.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertFalse(res["alert_triggered"], "No alert should fire when price is unchanged")
        self.assertEqual(res["trigger_reason"], "Price unchanged")
        self.assertEqual(res["new_price"], 1000.0)

    def test_scenario_2_small_price_drop(self):
        """Test 2: Old: $1000, New: $990, Threshold: 5% -> Result: No alert (1% drop does not reach 5%)"""
        url = "https://www.example.com/scenario-test-item-2"
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 2",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0
        )
        price_scraper.set_simulated_price(url, 990.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertFalse(res["alert_triggered"], "No alert should fire when drop (1%) is below 5% threshold")
        self.assertEqual(res["new_price"], 990.0)
        self.assertIn("below threshold", res["trigger_reason"].lower())

    def test_scenario_3_threshold_reached(self):
        """Test 3: Old: $1000, New: $950, Threshold: 5% -> Result: Send alert (5% drop >= 5%)"""
        url = "https://www.example.com/scenario-test-item-3"
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 3",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0
        )
        price_scraper.set_simulated_price(url, 950.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertTrue(res["alert_triggered"], "Alert must fire when drop exactly reaches 5% threshold")
        self.assertEqual(res["new_price"], 950.0)
        self.assertEqual(res["drop_amount"], 50.0)
        self.assertEqual(res["drop_percentage"], 5.0)

    def test_scenario_4_threshold_exceeded(self):
        """Test 4: Old: $1000, New: $900, Threshold: 5% -> Result: Send alert (10% drop >= 5%)"""
        url = "https://www.example.com/scenario-test-item-4"
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 4",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0
        )
        price_scraper.set_simulated_price(url, 900.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertTrue(res["alert_triggered"], "Alert must fire when drop (10%) exceeds 5% threshold")
        self.assertEqual(res["new_price"], 900.0)
        self.assertEqual(res["drop_amount"], 100.0)
        self.assertEqual(res["drop_percentage"], 10.0)

    def test_scenario_5_price_increase(self):
        """Test 5: Old: $950, New: $1000 -> Result: No alert (price increase)"""
        url = "https://www.example.com/scenario-test-item-5"
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 5",
            product_url=url,
            website="ExampleStore",
            current_price=950.0,
            original_price=950.0,
            currency="USD",
            alert_threshold=5.0
        )
        price_scraper.set_simulated_price(url, 1000.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertFalse(res["alert_triggered"], "Price increases must never trigger a price-drop alert")
        self.assertEqual(res["trigger_reason"], "Price increased")
        self.assertEqual(res["new_price"], 1000.0)
        # Verify DB updated current price
        db_prod = tracker_db.get_tracked_product(prod["id"])
        self.assertEqual(db_prod["current_price"], 1000.0)

    def test_scenario_6_minimum_amount_setting(self):
        """
        Test 6: Product: $1000, Min Amount Setting: $1000, New: $999.
        System must recognize price decrease and process alert rules without requiring full $1000 drop.
        """
        url = "https://www.example.com/scenario-test-item-6"
        # User sets Minimum Price Drop Amount to 1000
        tracker_db.update_user_settings({"min_price_drop_amount": "1000"})
        prod = tracker_db.add_tracked_product(
            product_name="Scenario Product 6",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD"
        )
        price_scraper.set_simulated_price(url, 999.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertTrue(res["alert_triggered"], "System must recognize price drop under ceiling threshold")
        self.assertEqual(res["new_price"], 999.0)
        self.assertEqual(res["drop_amount"], 1.0)

    def test_scenario_7_exact_product_tracking(self):
        """
        Test 7: User asks to track specific product -> only that exact product is tracked.
        No category items, similar products, or search results are tracked.
        """
        exact_url = "https://www.example.com/scenario-test-iphone-16-pro"
        active_prod = {
            "name": "Apple iPhone 16 Pro 256GB",
            "price": 1199.0,
            "currency": "USD",
            "url": exact_url,
            "website": "AppleStore"
        }
        res = client.post("/api/extension/chat", json={
            "message": "Track this iPhone 16 Pro",
            "active_product": active_prod
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("tracked_product_added"))

        # Verify only this exact product URL is in tracked products
        all_tracked = tracker_db.get_tracked_products()
        matching = [p for p in all_tracked if p["product_url"] == exact_url]
        self.assertEqual(len(matching), 1, "Exactly one tracking record must be created for the requested product")
        self.assertEqual(matching[0]["product_name"], "Apple iPhone 16 Pro 256GB")
        self.assertEqual(matching[0]["current_price"], 1199.0)

    def test_email_notification_fields(self):
        """Verify email notification contains all required fields from Section 8"""
        result = email_service.send_price_drop_alert(
            product_id="test-pid-999",
            product_name="Sony WH-1000XM5 Headphones",
            product_url="https://www.sony.com/scenario-test-headphones",
            current_price=349.99,
            previous_price=399.99,
            website="Sony Store",
            currency="USD",
            recipient_email="shopper@example.com",
            drop_amount=50.0,
            drop_percentage=12.5,
            timestamp=1700000000.0
        )
        self.assertTrue(result.get("success"))
        body = result.get("body", "")
        # Required Section 8 fields
        self.assertIn("Sony WH-1000XM5 Headphones", body, "Email must contain Product Name")
        self.assertIn("399.99", body, "Email must contain Previous Price")
        self.assertIn("349.99", body, "Email must contain New / Current Price")
        self.assertIn("50", body, "Email must contain Amount Dropped")
        self.assertIn("12.5%", body, "Email must contain Percentage Dropped")
        self.assertIn("Sony Store", body, "Email must contain Website")
        self.assertIn("https://www.sony.com/scenario-test-headphones", body, "Email must contain Product URL")
        self.assertIn("Time of Price Drop", body, "Email must contain Time of Price Drop")

    def test_database_stored_fields(self):
        """Verify database maintains all required product state fields from Section 3"""
        url = "https://www.example.com/scenario-test-db-state"
        prod = tracker_db.add_tracked_product(
            product_name="State Test Product",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0,
            user_email="state_user@example.com"
        )
        prod_id = prod["id"]
        db_prod = tracker_db.get_tracked_product(prod_id)

        # Section 3 required fields
        self.assertEqual(db_prod["product_url"], url)
        self.assertEqual(db_prod["product_name"], "State Test Product")
        self.assertEqual(db_prod["website"], "ExampleStore")
        self.assertEqual(db_prod["current_price"], 1000.0)
        self.assertEqual(db_prod["previous_price"], 1000.0)
        self.assertEqual(db_prod["original_price"], 1000.0)
        self.assertEqual(db_prod["currency"], "USD")
        self.assertEqual(db_prod["last_checked_price"], 1000.0)
        self.assertIsNotNone(db_prod["last_checked"])
        self.assertEqual(db_prod["alert_threshold"], 5.0)
        self.assertEqual(db_prod["alert_status"], "active")
        self.assertEqual(db_prod["user_email"], "state_user@example.com")

        history = tracker_db.get_price_history(prod_id)
        self.assertGreaterEqual(len(history), 1, "Price history must be maintained")
        self.assertEqual(history[0]["price"], 1000.0)

    def test_duplicate_alert_suppression(self):
        """
        Verify alert deduplication from Section 10:
        1. Alert triggered at $1000 -> $950
        2. Next check: price remains $950 -> Duplicate suppressed
        3. Next check: price drops to $900 -> New alert sent
        """
        url = "https://www.example.com/scenario-test-dedup"
        prod = tracker_db.add_tracked_product(
            product_name="Dedup Test Item",
            product_url=url,
            website="ExampleStore",
            current_price=1000.0,
            original_price=1000.0,
            currency="USD",
            alert_threshold=5.0
        )
        prod_id = prod["id"]

        # Step 1: Price drops to 950 -> Alert triggered
        price_scraper.set_simulated_price(url, 950.0, "USD")
        res1 = tracker_scheduler.check_product_price(prod)
        self.assertTrue(res1["alert_triggered"])
        self.assertEqual(res1["new_price"], 950.0)

        # Step 2: Next check at 950 -> Duplicate suppressed
        refreshed = tracker_db.get_tracked_product(prod_id)
        res2 = tracker_scheduler.check_product_price(refreshed)
        self.assertFalse(res2["alert_triggered"], "Duplicate alert must be suppressed")
        self.assertEqual(res2["trigger_reason"], "Duplicate alert suppressed")

        # Step 3: Next check at 900 -> Further drop triggers new alert
        price_scraper.set_simulated_price(url, 900.0, "USD")
        refreshed2 = tracker_db.get_tracked_product(prod_id)
        res3 = tracker_scheduler.check_product_price(refreshed2)
        self.assertTrue(res3["alert_triggered"], "Further price drop must trigger new alert")
        self.assertEqual(res3["new_price"], 900.0)

    def test_five_minute_scheduler_configuration(self):
        """Requirement 1: Verify 5-minute price check interval across backend and extension"""
        self.assertEqual(tracker_scheduler._interval_seconds, 300, "Backend scheduler default interval must be 300 seconds (5 minutes)")

        with open("chrome-extension/background.js", "r", encoding="utf-8") as f:
            bg_code = f.read()
        self.assertIn("periodInMinutes: 5", bg_code, "Chrome extension alarm period must be 5 minutes")

    def test_multi_product_page_tracks_only_selected_product(self):
        """
        Requirement 2: If webpage contains 5 products (A, B, C, D, E) and user selects Product C,
        the system must track ONLY Product C and NOT Products A, B, D, or E.
        Rule: ONE USER-SELECTED PRODUCT = ONE TRACKING RECORD = ONE EXACT PRODUCT URL
        """
        page_items = [
            {"name": "Product A", "url": "https://www.daraz.pk/products/item-a-11.html", "price": 1000.0, "website": "Daraz"},
            {"name": "Product B", "url": "https://www.daraz.pk/products/item-b-22.html", "price": 2000.0, "website": "Daraz"},
            {"name": "Product C", "url": "https://www.daraz.pk/products/scenario-test-item-c-33.html", "price": 3000.0, "website": "Daraz"},
            {"name": "Product D", "url": "https://www.daraz.pk/products/item-d-44.html", "price": 4000.0, "website": "Daraz"},
            {"name": "Product E", "url": "https://www.daraz.pk/products/item-e-55.html", "price": 5000.0, "website": "Daraz"},
        ]

        res = client.post("/api/extension/chat", json={
            "message": "Track Product C",
            "page_products": page_items
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("tracked_product_added"))
        self.assertEqual(data["product"]["product_name"], "Product C")
        self.assertEqual(data["product"]["product_url"], "https://www.daraz.pk/products/scenario-test-item-c-33.html")

        # Verify only Product C is in database among these
        all_prods = tracker_db.get_all_tracked_products()
        urls_in_db = [p["product_url"] for p in all_prods]
        self.assertIn("https://www.daraz.pk/products/scenario-test-item-c-33.html", urls_in_db)
        self.assertNotIn("https://www.daraz.pk/products/item-a-11.html", urls_in_db)
        self.assertNotIn("https://www.daraz.pk/products/item-b-22.html", urls_in_db)
        self.assertNotIn("https://www.daraz.pk/products/item-d-44.html", urls_in_db)
        self.assertNotIn("https://www.daraz.pk/products/item-e-55.html", urls_in_db)

    def test_product_url_validation(self):
        """
        Requirement: Before saving a product for tracking, verify that the extracted URL belongs to the selected product.
        If the exact product URL cannot be identified, do NOT start tracking.
        Must report: 'I couldn't identify the exact product page, so I can't safely track this product.'
        """
        # Generic search page
        res1 = client.post("/api/extension/chat", json={
            "message": "Track this product",
            "active_product": {
                "name": "Generic Search",
                "price": 1000.0,
                "url": "https://www.daraz.pk/catalog/?q=laptop"
            }
        })
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.json().get("tracked_product_added"))
        self.assertIn("I couldn't identify the exact product page, so I can't safely track this product.", res1.json()["reply"])

        # Direct API endpoint rejection
        res2 = client.post("/api/track-product", json={
            "product_name": "Invalid Search Item",
            "product_url": "https://www.amazon.com/s?k=iphone",
            "current_price": 999.0
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn("I couldn't identify the exact product page, so I can't safely track this product.", res2.json()["detail"])

    def test_product_unavailable_behavior(self):
        """
        Requirement: If the exact tracked product URL becomes unavailable, do not automatically replace it with another product.
        Show: 'The tracked product is currently unavailable or could not be found.'
        """
        url = "https://www.store.com/scenario-test-item-unavailable-99"
        prod = tracker_db.add_tracked_product(
            product_name="Unavailable Test Gadget",
            product_url=url,
            website="Store",
            current_price=500.0,
            original_price=500.0,
            currency="USD"
        )
        prod_id = prod["id"]

        # Simulate product becoming unavailable (no price returned / 0)
        price_scraper.set_simulated_price(url, 0.0, "USD")
        res = tracker_scheduler.check_product_price(prod)

        self.assertFalse(res["alert_triggered"])
        self.assertEqual(res["status"], "unavailable")
        expected_msg = "The tracked product is currently unavailable or could not be found."
        self.assertEqual(res["trigger_reason"], expected_msg)

        # Verify DB updated tracking_status to unavailable without substituting another product
        refreshed = tracker_db.get_tracked_product(prod_id)
        self.assertEqual(refreshed["tracking_status"], "unavailable")
        self.assertEqual(refreshed["product_url"], url, "Must never replace the product URL")

    def test_product_identity_json_schema(self):
        """
        Requirement: Store and return Product Identity schema:
        { productId, productName, productUrl, website, currentPrice, currency, trackingEnabled }
        """
        url = "https://www.daraz.pk/products/scenario-test-schema-item-88.html"
        prod = tracker_db.add_tracked_product(
            product_name="Schema Test Phone",
            product_url=url,
            website="Daraz",
            current_price=180000.0,
            currency="PKR"
        )
        self.assertEqual(prod["productId"], prod["id"])
        self.assertEqual(prod["productName"], "Schema Test Phone")
        self.assertEqual(prod["productUrl"], url)
        self.assertEqual(prod["website"], "Daraz")
        self.assertEqual(prod["currentPrice"], 180000.0)
        self.assertEqual(prod["currency"], "PKR")
        self.assertTrue(prod["trackingEnabled"])

    def test_tracking_interface_elements_in_extension(self):
        """Requirement 7: Tracking interface contains all required elements for exact product"""
        from bs4 import BeautifulSoup
        with open("chrome-extension/popup.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        card = soup.find("div", {"id": "dedicated-tracking-card"})
        self.assertIsNotNone(card, "#dedicated-tracking-card must exist")

        # Verify all required display fields
        self.assertIsNotNone(card.find(id="dedicated-product-image"), "Must display product image")
        self.assertIsNotNone(card.find(id="dedicated-product-name"), "Must display product name")
        self.assertIsNotNone(card.find(id="dedicated-website"), "Must display website")
        self.assertIsNotNone(card.find(id="dedicated-brand-model"), "Must display brand/model")
        self.assertIsNotNone(card.find(id="dedicated-current-price"), "Must display current price")
        self.assertIsNotNone(card.find(id="dedicated-previous-price"), "Must display previous price")
        self.assertIsNotNone(card.find(id="dedicated-price-change"), "Must display price change")
        self.assertIsNotNone(card.find(id="dedicated-status"), "Must display tracking status")
        self.assertIsNotNone(card.find(id="dedicated-last-checked"), "Must display last checked time")
        self.assertIsNotNone(card.find(id="dedicated-target-price"), "Must display target price")
        self.assertIsNotNone(card.find(id="btn-dedicated-view"), "Must have view product action")
        self.assertIsNotNone(card.find(id="btn-dedicated-stop"), "Must have stop tracking action")
        self.assertIsNotNone(soup.find(id="multi-product-card"), "Must have multi-product selection card")


class TestShopAIAssistantProductTracking(unittest.TestCase):
    """
    Tests for ShopAI Assistant product tracking:
    - Products returned by ShopAI Assistant are trackable via the extension.
    - All 4 tracking phrases supported: 'Track this product', 'Track this item', 'Track the price', 'Start tracking this'.
    - Complete product data passed: ID, name, brand, model, exact URL, website, price, currency, image, specs.
    - Only exact selected product tracked.
    - Same 5-minute scheduler, price history, and browser notifications.
    - Products without valid URL rejected with clear message.
    - Both Website Tracking and ShopAI Assistant Tracking flows supported.
    """

    def setUp(self):
        tracker_db.init_db()
        ProductPriceScraper.clear_simulated_prices()

    def tearDown(self):
        ProductPriceScraper.clear_simulated_prices()

    def test_track_product_phrases_from_shopai_assistant(self):
        """
        Requirement 1: User says:
        - 'Track this product'
        - 'Track this item'
        - 'Track the price'
        - 'Start tracking this'
        The extension must recognize that the user is referring to the exact product returned by ShopAI Assistant.
        """
        phrases = [
            "Track this product",
            "Track this item",
            "Track the price",
            "Start tracking this"
        ]

        for idx, phrase in enumerate(phrases, 1):
            asst_prod = {
                "id": 100 + idx,
                "name": f"ShopAI Test Laptop {idx}",
                "brand": "Dell",
                "model": f"XPS-13-{idx}",
                "url": f"https://dummyjson.com/products/{100 + idx}",
                "product_url": f"https://dummyjson.com/products/{100 + idx}",
                "website": "ShopAI Store",
                "price": 1299.0 + idx,
                "currency": "USD",
                "image": "https://cdn.dummyjson.com/products/laptop.jpg",
                "specifications": {"ram": "16GB", "storage": "512GB SSD"}
            }

            res = client.post("/api/extension/chat", json={
                "message": phrase,
                "last_assistant_product": asst_prod
            })

            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("tracked_product_added"), f"Failed for phrase: '{phrase}'")
            self.assertEqual(data["product"]["product_name"], f"ShopAI Test Laptop {idx}")
            self.assertEqual(data["product"]["product_url"], f"https://dummyjson.com/products/{100 + idx}")

    def test_complete_product_data_passed_to_tracking_system(self):
        """
        Requirement 2: Pass complete product data:
        - Product ID, Product name, Brand, Model, Exact product URL, Website/store,
          Current price, Currency, Product image, Specifications.
        The tracking system must use the exact product URL or unique ID as identity.
        """
        asst_prod = {
            "id": 42,
            "name": "Sony WH-1000XM5 Noise Canceling Headphones",
            "brand": "Sony",
            "model": "WH-1000XM5",
            "url": "https://dummyjson.com/products/42",
            "product_url": "https://dummyjson.com/products/42",
            "website": "ShopAI Store",
            "price": 399.0,
            "currency": "USD",
            "image": "https://cdn.dummyjson.com/products/sony-wh.jpg",
            "specifications": {"battery": "30h", "connectivity": "Bluetooth 5.2", "anc": True}
        }

        res = client.post("/api/extension/chat", json={
            "message": "Track this product and alert me below $350",
            "last_assistant_product": asst_prod
        })

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["tracked_product_added"])
        p = data["product"]

        # Validate all required fields
        self.assertEqual(p["product_name"], "Sony WH-1000XM5 Noise Canceling Headphones")
        self.assertEqual(p["brand"], "Sony")
        self.assertEqual(p["model"], "WH-1000XM5")
        self.assertEqual(p["product_url"], "https://dummyjson.com/products/42")
        self.assertIn("ShopAI", p["website"])
        self.assertEqual(p["currency"], "USD")
        self.assertEqual(p["image_url"], "https://cdn.dummyjson.com/products/sony-wh.jpg")
        self.assertEqual(p["target_price"], 350.0)

        # Specifications preserved
        specs = json.loads(p["specifications"]) if isinstance(p["specifications"], str) else p["specifications"]
        self.assertEqual(specs.get("productId"), 42)
        self.assertEqual(specs.get("battery"), "30h")

        # Identity schema
        rec = data["tracking_record"]
        self.assertEqual(rec["productUrl"], "https://dummyjson.com/products/42")
        self.assertEqual(rec["productName"], "Sony WH-1000XM5 Noise Canceling Headphones")

    def test_do_not_track_different_or_multiple_products(self):
        """
        Requirement 3: Never track all returned products, similar products, or replace the product.
        Track ONLY the exact product selected by the user.
        """
        asst_prod = {
            "id": 7,
            "name": "Apple MacBook Pro 14 M2",
            "brand": "Apple",
            "model": "MBP-14-M2",
            "url": "https://dummyjson.com/products/7",
            "product_url": "https://dummyjson.com/products/7",
            "website": "ShopAI Store",
            "price": 1999.0,
            "currency": "USD"
        }

        # User is viewing an arbitrary webpage, but asks to track the ShopAI assistant product
        res = client.post("/api/extension/chat", json={
            "message": "Track this product",
            "last_assistant_product": asst_prod,
            "page_products": [
                {"name": "Other Laptop A", "url": "https://www.daraz.pk/products/laptop-a.html", "price": 500.0},
                {"name": "Other Laptop B", "url": "https://www.daraz.pk/products/laptop-b.html", "price": 600.0}
            ]
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["tracked_product_added"])
        self.assertEqual(data["product"]["product_url"], "https://dummyjson.com/products/7")
        self.assertEqual(data["product"]["product_name"], "Apple MacBook Pro 14 M2")

        # Confirm database contains only this exact product and neither of the other laptops
        all_prods = tracker_db.get_all_tracked_products()
        urls = [item["product_url"] for item in all_prods]
        self.assertIn("https://dummyjson.com/products/7", urls)
        self.assertNotIn("https://www.daraz.pk/products/laptop-a.html", urls)
        self.assertNotIn("https://www.daraz.pk/products/laptop-b.html", urls)

    def test_same_tracking_system_5min_check_and_browser_alert(self):
        """
        Requirement 4, 6, 7: Products added through ShopAI Assistant use the exact same
        tracking infrastructure, 5-minute background check, and browser notifications on drop.
        """
        url = "https://dummyjson.com/products/50-headphones-scenario"
        ProductPriceScraper.set_simulated_price(url, 399.0, "USD")

        # Track via ShopAI assistant flow
        res = client.post("/api/extension/chat", json={
            "message": "Start tracking this",
            "last_assistant_product": {
                "id": 50,
                "name": "Sony WH-1000XM5",
                "brand": "Sony",
                "model": "XM5",
                "url": url,
                "product_url": url,
                "website": "ShopAI Store",
                "price": 399.0,
                "currency": "USD"
            }
        })
        self.assertEqual(res.status_code, 200)
        prod_id = res.json()["product"]["id"]

        # Simulate price drop to $349 ($50 drop, ~12.53%)
        ProductPriceScraper.set_simulated_price(url, 349.0, "USD")

        # Execute scheduler check
        results = tracker_scheduler.check_all_tracked_products()
        matching = [r for r in results if r["product_id"] == prod_id]
        self.assertTrue(len(matching) == 1)
        r = matching[0]

        self.assertTrue(r["alert_triggered"], "Alert must trigger on price drop")
        self.assertEqual(r["previous_price"], 399.0)
        self.assertEqual(r["new_price"], 349.0)
        self.assertAlmostEqual(r["drop_amount"], 50.0, places=1)
        self.assertAlmostEqual(r["drop_percentage"], 12.53, places=1)

        # Verify browser notification is queued in pending notifications
        notifs = tracker_db.get_pending_browser_notifications()
        matching_notifs = [n for n in notifs if n["product_id"] == prod_id]
        self.assertTrue(len(matching_notifs) >= 1)
        notif = matching_notifs[0]
        self.assertEqual(notif["product_name"], "Sony WH-1000XM5")
        self.assertAlmostEqual(notif["current_price"], 349.0, places=1)
        self.assertAlmostEqual(notif["previous_price"], 399.0, places=1)

    def test_shopai_product_without_valid_url_rejected_with_exact_message(self):
        """
        Requirement 8: If ShopAI Assistant returns a product without a valid product URL,
        do not silently track another product. Clearly tell the user that the product cannot
        be tracked until a valid product URL is available.
        """
        # Missing URL
        res1 = client.post("/api/extension/chat", json={
            "message": "Track this product",
            "last_assistant_product": {
                "id": 999,
                "name": "Product Without URL",
                "price": 50.0,
                "url": None,
                "product_url": None,
                "website": "ShopAI Store"
            }
        })
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.json().get("tracked_product_added"))
        self.assertIn(
            "This product does not have a valid product URL, so it cannot be tracked until a valid product URL is available.",
            res1.json()["reply"]
        )

        # Invalid/empty URL
        res2 = client.post("/api/extension/chat", json={
            "message": "Track this item",
            "last_assistant_product": {
                "id": 999,
                "name": "Product With Empty URL",
                "price": 50.0,
                "url": "not-a-url",
                "product_url": "not-a-url",
                "website": "ShopAI Store"
            }
        })
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.json().get("tracked_product_added"))
        self.assertIn(
            "This product does not have a valid product URL, so it cannot be tracked until a valid product URL is available.",
            res2.json()["reply"]
        )

    def test_support_both_website_and_shopai_assistant_flows(self):
        """
        Requirement 10: The extension must support BOTH:
        A. Website Tracking (e.g. browsing Daraz product page)
        B. ShopAI Assistant Tracking (e.g. recommended by ShopAI assistant)
        Both flows create the same tracking record and monitor every 5 minutes.
        """
        # Flow A: Website Tracking
        res_a = client.post("/api/extension/chat", json={
            "message": "Track this product",
            "active_product": {
                "name": "Website Flow Phone",
                "url": "https://www.daraz.pk/products/flow-a-item-phone.html",
                "website": "Daraz",
                "price": 75000.0,
                "currency": "PKR"
            }
        })
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        self.assertTrue(data_a["tracked_product_added"])
        self.assertEqual(data_a["product"]["product_url"], "https://www.daraz.pk/products/flow-a-item-phone.html")

        # Flow B: ShopAI Assistant Tracking
        res_b = client.post("/api/extension/chat", json={
            "message": "Track this product",
            "last_assistant_product": {
                "id": 2,
                "name": "Eyeshadow Palette with Mirror",
                "brand": "Glamour Beauty",
                "url": "https://dummyjson.com/products/2",
                "product_url": "https://dummyjson.com/products/2",
                "website": "DummyJSON",
                "price": 19.99,
                "currency": "USD"
            }
        })
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        self.assertTrue(data_b["tracked_product_added"])
        self.assertEqual(data_b["product"]["product_url"], "https://dummyjson.com/products/2")

        # Verify both records are in SQLite and both can be updated/polled
        all_prods = tracker_db.get_all_tracked_products()
        urls = [p["product_url"] for p in all_prods]
        self.assertIn("https://www.daraz.pk/products/flow-a-item-phone.html", urls)
        self.assertIn("https://dummyjson.com/products/2", urls)


if __name__ == "__main__":
    unittest.main()



