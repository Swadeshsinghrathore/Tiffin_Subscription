import os
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from flask import current_app, g, has_app_context
except ImportError:
    current_app = None
    g = None
    has_app_context = lambda: False

DEFAULT_DB_FILENAME = "tiffin.db"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve SQLite database path."""
    if custom_path:
        return custom_path
    if has_app_context() and current_app and "DATABASE" in current_app.config:
        return current_app.config["DATABASE"]
    return os.path.join(os.getcwd(), DEFAULT_DB_FILENAME)


def get_db(custom_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Get a SQLite connection with Row factory and FK pragma enabled.
    Reuses connection on Flask `g` if inside an active application context.
    """
    db_path = get_db_path(custom_path)

    if has_app_context():
        if "_database" not in g:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            g._database = conn
        return g._database

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def close_db(e=None):
    """Close the database connection on app context teardown."""
    if has_app_context():
        db = g.pop("_database", None)
        if db is not None:
            db.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database with schema.sql and default seed plans."""
    conn = get_db(db_path)
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    # Seed default plans if table is empty
    cur = conn.execute("SELECT COUNT(*) FROM plans")
    count = cur.fetchone()[0]
    if count == 0:
        default_plans = [
            ("STD_VEG", "Standard Veg", 300000),    # ₹3,000 / month
            ("DLX_VEG", "Deluxe Veg", 380000),      # ₹3,800 / month
            ("MINI_MEAL", "Mini Meal", 220000),     # ₹2,200 / month
        ]
        conn.executemany(
            "INSERT INTO plans (code, name, monthly_price_paise, is_active) VALUES (?, ?, ?, 1)",
            default_plans,
        )
        conn.commit()

    # Schema migration checks for existing databases
    # 1. Check if email column exists in customers
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(customers)").fetchall()]
    if "email" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN email TEXT")
        conn.commit()

    # 2. Populate default emails for any customers without one
    cust_rows = conn.execute("SELECT id, name, phone, email FROM customers WHERE email IS NULL OR email = ''").fetchall()
    for row in cust_rows:
        clean_name = row["name"].lower().replace(" ", ".")
        auto_email = f"{clean_name}@example.com"
        conn.execute("UPDATE customers SET email = ? WHERE id = ?", (auto_email, row["id"]))
    if cust_rows:
        conn.commit()

    # 3. Ensure subscription_transfers table exists
    conn.execute("""
    CREATE TABLE IF NOT EXISTS subscription_transfers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      from_customer_id INTEGER NOT NULL REFERENCES customers(id),
      to_customer_id INTEGER NOT NULL REFERENCES customers(id),
      transfer_date TEXT NOT NULL,
      plan_id INTEGER NOT NULL REFERENCES plans(id),
      reason TEXT,
      created_at TEXT NOT NULL
    )
    """)
    conn.commit()

    # Seed default demo owner if owners table is empty
    cur_owner = conn.execute("SELECT COUNT(*) FROM owners")
    owner_count = cur_owner.fetchone()[0]
    if owner_count == 0:
        from werkzeug.security import generate_password_hash
        from datetime import datetime
        now_iso = datetime.now().isoformat(timespec="seconds")
        demo_pass_hash = generate_password_hash("tiffin123")
        conn.execute(
            """
            INSERT INTO owners (username, email, password_hash, business_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("admin", "owner@tiffinbox.com", demo_pass_hash, "Annapurna Tiffin Kitchen", now_iso),
        )
        conn.commit()

    if not has_app_context():
        conn.close()

