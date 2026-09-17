CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  monthly_price_paise INTEGER NOT NULL,      -- money as integer paise, never REAL
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT UNIQUE NOT NULL,                -- normalised 10-digit; the lookup key
  name TEXT NOT NULL,
  email TEXT,                                -- customer email for 9 AM delivery notifications
  address TEXT,
  plan_id INTEGER NOT NULL REFERENCES plans(id),
  start_date TEXT NOT NULL,                  -- ISO YYYY-MM-DD
  end_date TEXT,                             -- NULL = ongoing
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pauses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  start_date TEXT NOT NULL,
  end_date TEXT,                             -- NULL = open-ended, still paused
  reason TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pauses_customer ON pauses(customer_id);

CREATE TABLE IF NOT EXISTS holidays (        -- service closed: excluded from BOTH numerator and denominator
  day TEXT PRIMARY KEY,
  label TEXT
);

CREATE TABLE IF NOT EXISTS bills (           -- frozen month-end snapshot
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  plan_price_paise INTEGER NOT NULL,
  billable_days INTEGER NOT NULL,
  delivered_days INTEGER NOT NULL,
  paused_days INTEGER NOT NULL,
  amount_paise INTEGER NOT NULL,
  generated_at TEXT NOT NULL,
  UNIQUE(customer_id, year, month)
);

CREATE TABLE IF NOT EXISTS owners (          -- business owner accounts
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  business_name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  recipient_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  delivery_date TEXT NOT NULL,
  status TEXT NOT NULL,                      -- 'sent', 'logged', 'failed'
  details TEXT,
  sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_date ON notification_logs(delivery_date);

CREATE TABLE IF NOT EXISTS subscription_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_customer_id INTEGER NOT NULL REFERENCES customers(id),
  to_customer_id INTEGER NOT NULL REFERENCES customers(id),
  transfer_date TEXT NOT NULL,                -- First date new customer receives food
  plan_id INTEGER NOT NULL REFERENCES plans(id),
  reason TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transfers_from ON subscription_transfers(from_customer_id);
CREATE INDEX IF NOT EXISTS idx_transfers_to ON subscription_transfers(to_customer_id);
