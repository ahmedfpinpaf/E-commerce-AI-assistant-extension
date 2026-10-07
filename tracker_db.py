import sqlite3
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.db")

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Tracked products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_products (
                id TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                brand TEXT,
                model TEXT,
                product_url TEXT NOT NULL UNIQUE,
                website TEXT NOT NULL,
                image_url TEXT,
                current_price REAL NOT NULL,
                previous_price REAL,
                original_price REAL,
                currency TEXT NOT NULL DEFAULT 'PKR',
                target_price REAL,
                alert_threshold REAL,
                tracking_status TEXT NOT NULL DEFAULT 'active',
                alert_status TEXT NOT NULL DEFAULT 'active',
                alert_type TEXT NOT NULL DEFAULT 'target_price',
                last_checked REAL,
                last_checked_price REAL,
                last_price_change REAL,
                last_alert_sent REAL,
                last_alert_price REAL,
                user_email TEXT,
                specifications TEXT,
                created_at REAL NOT NULL
            )
        """)

        # Migration: ensure new columns exist in pre-existing tracked_products tables
        cursor.execute("PRAGMA table_info(tracked_products)")
        existing_cols = [row["name"] for row in cursor.fetchall()]
        if "original_price" not in existing_cols:
            cursor.execute("ALTER TABLE tracked_products ADD COLUMN original_price REAL")
        if "last_checked_price" not in existing_cols:
            cursor.execute("ALTER TABLE tracked_products ADD COLUMN last_checked_price REAL")
        if "alert_threshold" not in existing_cols:
            cursor.execute("ALTER TABLE tracked_products ADD COLUMN alert_threshold REAL")
        if "alert_status" not in existing_cols:
            cursor.execute("ALTER TABLE tracked_products ADD COLUMN alert_status TEXT DEFAULT 'active'")
        if "user_email" not in existing_cols:
            cursor.execute("ALTER TABLE tracked_products ADD COLUMN user_email TEXT")
        
        # 2. Price history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (product_id) REFERENCES tracked_products(id) ON DELETE CASCADE
            )
        """)
        
        # 3. User settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        # 4. Alert log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                previous_price REAL,
                current_price REAL NOT NULL,
                target_price REAL,
                currency TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                sent_at REAL NOT NULL,
                status TEXT NOT NULL,
                drop_amount REAL,
                drop_percentage REAL
            )
        """)

        cursor.execute("PRAGMA table_info(alert_logs)")
        alert_cols = [row["name"] for row in cursor.fetchall()]
        if "drop_amount" not in alert_cols:
            cursor.execute("ALTER TABLE alert_logs ADD COLUMN drop_amount REAL")
        if "drop_percentage" not in alert_cols:
            cursor.execute("ALTER TABLE alert_logs ADD COLUMN drop_percentage REAL")
        
        # Default user settings if not present
        defaults = {
            "alert_email": "user@example.com",
            "check_interval_minutes": "5",
            "notifications_enabled": "true",
            "price_drop_alerts_enabled": "true",
            "tracked_alerts_enabled": "true",
            "price_drop_pct_threshold": "5",
            "min_price_drop_amount": "0",
            "alert_frequency": "immediately",
            "browser_notifications_enabled": "true",
            "email_notifications_enabled": "true",
            "email_alert_preferences": "all"
        }
        for k, v in defaults.items():
            cursor.execute("SELECT value FROM user_settings WHERE key = ?", (k,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO user_settings (key, value) VALUES (?, ?)", (k, v))
            
        conn.commit()

# Product CRUD
def add_tracked_product(
    product_name: str,
    product_url: str,
    website: str,
    current_price: float,
    currency: str = "PKR",
    brand: Optional[str] = None,
    model: Optional[str] = None,
    image_url: Optional[str] = None,
    target_price: Optional[float] = None,
    alert_type: str = "target_price",
    specifications: Optional[Dict[str, Any]] = None,
    original_price: Optional[float] = None,
    alert_threshold: Optional[float] = None,
    user_email: Optional[str] = None
) -> Dict[str, Any]:
    now = time.time()
    prod_id = str(uuid.uuid4())
    specs_json = json.dumps(specifications or {})
    orig_p = float(original_price) if original_price is not None else float(current_price)
    
    settings = get_user_settings()
    default_email = user_email or settings.get("alert_email", "user@example.com")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if URL already tracked
        cursor.execute("SELECT id, original_price FROM tracked_products WHERE product_url = ?", (product_url,))
        existing = cursor.fetchone()
        if existing:
            # Update existing product target price / current price while keeping original_price intact
            cursor.execute("""
                UPDATE tracked_products
                SET current_price = ?, previous_price = ?, target_price = COALESCE(?, target_price),
                    alert_threshold = COALESCE(?, alert_threshold),
                    user_email = COALESCE(?, user_email),
                    alert_type = COALESCE(?, alert_type), tracking_status = 'active',
                    alert_status = 'active', last_checked = ?, last_checked_price = ?,
                    last_alert_price = NULL, last_alert_sent = NULL
                WHERE id = ?
            """, (current_price, current_price, target_price, alert_threshold, default_email, alert_type, now, current_price, existing["id"]))
            conn.commit()
            return get_tracked_product(existing["id"])
        
        cursor.execute("""
            INSERT INTO tracked_products (
                id, product_name, brand, model, product_url, website, image_url,
                current_price, previous_price, original_price, currency, target_price,
                alert_threshold, tracking_status, alert_status, alert_type, last_checked,
                last_checked_price, last_price_change, last_alert_sent, last_alert_price,
                user_email, specifications, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prod_id, product_name, brand or "N/A", model or "N/A", product_url, website,
            image_url or "", current_price, current_price, orig_p, currency, target_price,
            alert_threshold, "active", "active", alert_type, now,
            current_price, now, None, None,
            default_email, specs_json, now
        ))
        
        # Initial price history entry
        cursor.execute("""
            INSERT INTO price_history (product_id, price, currency, timestamp)
            VALUES (?, ?, ?, ?)
        """, (prod_id, current_price, currency, now))
        
        conn.commit()
        
    return get_tracked_product(prod_id)

def _format_tracked_dict(row) -> Dict[str, Any]:
    d = dict(row)
    # Product Identity schema fields (Section 2)
    d["productId"] = d.get("id")
    d["productName"] = d.get("product_name")
    d["productUrl"] = d.get("product_url")
    d["currentPrice"] = d.get("current_price")
    d["trackingEnabled"] = (d.get("tracking_status") == "active")
    return d

def get_tracked_product(prod_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracked_products WHERE id = ?", (prod_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _format_tracked_dict(row)

def get_all_tracked_products() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracked_products ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [_format_tracked_dict(r) for r in rows]

get_tracked_products = get_all_tracked_products

def update_tracked_product(
    prod_id: str,
    target_price: Optional[float] = None,
    tracking_status: Optional[str] = None,
    alert_type: Optional[str] = None,
    alert_threshold: Optional[float] = None,
    user_email: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        
        if target_price is not None:
            updates.append("target_price = ?")
            params.append(target_price)
        if tracking_status is not None:
            updates.append("tracking_status = ?")
            params.append(tracking_status)
        if alert_type is not None:
            updates.append("alert_type = ?")
            params.append(alert_type)
        if alert_threshold is not None:
            updates.append("alert_threshold = ?")
            params.append(alert_threshold)
        if user_email is not None:
            updates.append("user_email = ?")
            params.append(user_email)
            
        if updates:
            params.append(prod_id)
            cursor.execute(f"UPDATE tracked_products SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            
    return get_tracked_product(prod_id)

def delete_tracked_product(prod_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracked_products WHERE id = ?", (prod_id,))
        cursor.execute("DELETE FROM price_history WHERE product_id = ?", (prod_id,))
        conn.commit()
        return cursor.rowcount > 0

def record_price_update(
    prod_id: str,
    new_price: float,
    currency: Optional[str] = None
) -> Dict[str, Any]:
    now = time.time()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT current_price, currency, original_price FROM tracked_products WHERE id = ?", (prod_id,))
        row = cursor.fetchone()
        if not row:
            return {}
            
        old_price = float(row["current_price"])
        curr = currency or row["currency"]
        price_changed = abs(new_price - old_price) > 0.01
        
        if price_changed:
            cursor.execute("""
                UPDATE tracked_products
                SET previous_price = current_price,
                    current_price = ?,
                    last_checked_price = ?,
                    currency = ?,
                    last_checked = ?,
                    last_price_change = ?
                WHERE id = ?
            """, (new_price, new_price, curr, now, now, prod_id))
            
            # Record in history
            cursor.execute("""
                INSERT INTO price_history (product_id, price, currency, timestamp)
                VALUES (?, ?, ?, ?)
            """, (prod_id, new_price, curr, now))
        else:
            cursor.execute("""
                UPDATE tracked_products
                SET last_checked = ?,
                    last_checked_price = ?
                WHERE id = ?
            """, (now, new_price, prod_id))
            
        conn.commit()
        
    return get_tracked_product(prod_id)

def record_alert_sent(
    prod_id: str,
    price: float,
    alert_type: str,
    recipient_email: str,
    subject: str,
    body: str,
    previous_price: Optional[float] = None,
    drop_amount: Optional[float] = None,
    drop_percentage: Optional[float] = None
):
    now = time.time()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracked_products
            SET last_alert_sent = ?,
                last_alert_price = ?,
                tracking_status = 'alert_triggered',
                alert_status = 'alert_triggered'
            WHERE id = ?
        """, (now, price, prod_id))
        
        cursor.execute("SELECT product_name, previous_price, target_price, currency FROM tracked_products WHERE id = ?", (prod_id,))
        row = cursor.fetchone()
        
        prev_p = previous_price if previous_price is not None else (row["previous_price"] if row else price)
        calc_drop = drop_amount if drop_amount is not None else max(0.0, prev_p - price)
        calc_pct = drop_percentage if drop_percentage is not None else ((calc_drop / prev_p * 100.0) if prev_p > 0 else 0.0)

        cursor.execute("""
            INSERT INTO alert_logs (
                product_id, product_name, alert_type, previous_price, current_price,
                target_price, currency, recipient_email, subject, body, sent_at, status,
                drop_amount, drop_percentage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prod_id,
            row["product_name"] if row else "Unknown",
            alert_type,
            prev_p,
            price,
            row["target_price"] if row else None,
            row["currency"] if row else "PKR",
            recipient_email,
            subject,
            body,
            now,
            "pending_browser",
            calc_drop,
            calc_pct
        ))
        conn.commit()

def get_pending_browser_notifications() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alert_logs WHERE status = 'pending_browser' ORDER BY sent_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def acknowledge_browser_notifications(log_ids: Optional[List[int]] = None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if log_ids:
            placeholders = ",".join(["?"] * len(log_ids))
            cursor.execute(f"UPDATE alert_logs SET status = 'acknowledged' WHERE id IN ({placeholders})", log_ids)
        else:
            cursor.execute("UPDATE alert_logs SET status = 'acknowledged' WHERE status = 'pending_browser'")
        conn.commit()

def get_price_history(prod_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM price_history WHERE product_id = ? ORDER BY timestamp ASC", (prod_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def get_alert_logs(limit: int = 50) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alert_logs ORDER BY sent_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

# Settings CRUD
def get_user_settings() -> Dict[str, str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM user_settings")
        return {r["key"]: r["value"] for r in cursor.fetchall()}

def update_user_settings(settings: Dict[str, str]):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for k, v in settings.items():
            cursor.execute("""
                INSERT INTO user_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (k, str(v)))
        conn.commit()

# Initialize DB when module loaded
init_db()
