# 🍱 TiffinBox — Automated Tiffin Subscriptions & Pro-Rated Billing Engine

A production-grade web application and automated service built for home-style tiffin (lunch delivery) businesses. Customers subscribe to monthly meal plans and receive freshly cooked lunches every weekday (Monday through Friday). Subscribers pause for travel, illness, or festivals and **must not be charged for paused days**. 

At month-end, the kitchen owner generates transparent, mathematically exact pro-rated billing sheets. The system features a **Customer Self-Service Portal**, an **Automated 9:00 AM Daily Delivery Notification Service** via Gmail SMTP, and a **Mid-Cycle Subscription Transfer Engine** that automatically splits billing by who was served.

---

## 🎯 The Core Billing Engine

### Mathematical Formula
```
billable_days  = delivery weekdays in month − service holidays        ← denominator (month-wide, SAME for every customer)
delivered_days = billable_days ∩ subscription window − paused dates   ← numerator (per customer)
amount         = plan_price × delivered_days / billable_days
```

### Why the Denominator is Month-Wide
If the denominator were each customer's own active window, a subscriber joining on the 14th would pay 100% of the monthly price for half a month of meals. By using the month's delivery weekdays as the uniform denominator, mid-month subscriptions pro-rate fairly against the month's total capacity.

### Three Mathematical Guarantees
1. **Exact Plan Price for Full Months:** When `delivered == billable`, the bill is **strictly** the plan price. Rounding never drifts a full month of ₹3,000 to ₹2,999.98.
2. **Never Touch a Float for Currency:** All prices and amounts are stored as integer **paise** (`1 Rupee = 100 paise`). Currency fractions are computed using Python's `Decimal` and quantized with `ROUND_HALF_UP` to whole paise.
3. **Multiply Before Dividing:** Avoid premature rounding of daily rates. Multiply `plan_price_paise * delivered_days` first, divide by `billable_days`, and round once at the end.

---

## 📅 Set Theory for Dates (`set[date]`)

Dates are modelled as discrete sets of `datetime.date` and combined with pure set operations. A month is $\le 31$ elements, making memory and execution instantaneous while eliminating classic calendar bugs:
- **Weekends are excluded by construction:** Pausing Friday $\to$ Monday deducts 2 delivery days, not 4 calendar days.
- **Set union automatically deduplicates:** Overlapping pauses (e.g. 5th–10th and 8th–12th) cannot double-deduct shared days.
- **Natural clipping:** A pause spanning month boundaries (Jan 28 $\to$ Feb 5) clips cleanly into January and February billing sheets.
- **Derived Status:** Customer status (`NOT_STARTED | ACTIVE | PAUSED | ENDED`) is a pure derived function: `status_on(customer, pauses, on_date)`. No mutable database flags that can desynchronize.

---

## 🔄 Mid-Cycle Subscription Transfer Feature

Transfer an active subscription mid-cycle to a new customer (e.g. roommate, friend, colleague taking over the flat):
1. **Cycle & Plan Carry-Over:**
   - Outgoing customer's service ends on $T - 1$ (`end_date = transfer_date - 1 day`).
   - Incoming customer is registered and starts on $T$ (`start_date = transfer_date`), inheriting the original plan and cycle end date.
   - Any active pause for the outgoing customer is capped at $T - 1$ so the incoming customer starts fresh and active.
2. **Exact Billing Split:**
   - Outgoing customer is billed strictly for delivered days from start until $T - 1$.
   - Incoming customer is billed strictly for delivered days from $T$ to cycle end.
   - Sum of both delivered days equals total cycle delivered days.
   - Both customers are linked in audit logs with bidirectional badges on profiles and billing sheets.

---

## 📬 Automated 9:00 AM Delivery Notification Service

Every morning at 9:00 AM, the background daemon thread queries subscribers due for delivery today:
- **Eligibility Rules:** Must be a weekday (Mon–Fri), non-holiday, active subscription, and not paused.
- **Email Delivery:** Dispatched via Gmail SMTP SSL (`smtp.gmail.com:465`) with HTML delivery cards (window 12:00 PM – 1:30 PM, meal plan name, address, customer portal link).
- **Audit Logging:** Every attempt is recorded in `notification_logs` with status (`sent`, `logged`, or `failed`).
- **Owner Controls:** Manual "Send Today's Notifications Now" trigger available on `/notifications`.

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- SQLite 3

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/Swadeshsinghrathore/Tiffin_Subscription.git
cd Tiffin_Subscription

# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate virtual environment (Linux / macOS)
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```
*(Dependencies: `flask>=3.0.0`, `pytest>=8.0.0`)*

### 3. Configure Environment Variables (`.env`)
Create a `.env` file in the project root:
```env
# Flask Configuration
SECRET_KEY=tiffin-super-secret-key-2026
FLASK_DEBUG=1

# Gmail SMTP Email Notification Credentials
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_USER=ssrathore.woork@gmail.com
SMTP_PASSWORD=ztamepzhkxjpploh
SMTP_FROM=TiffinBox Notifications <ssrathore.woork@gmail.com>
```

### 4. Initialize Database & Seed Demo Data
```bash
python -c "from tiffin.db import init_db; init_db()"
python seed_demo.py
```

### 5. Run the Application
```bash
python app.py
```
Or with Flask CLI:
```bash
flask --app app run --port 5000 --debug
```
The server will start at **http://127.0.0.1:5000/**.

---

## 🔑 Default Credentials

### Kitchen Owner Login
- **URL:** http://127.0.0.1:5000/login
- **Username:** `admin`
- **Password:** `tiffin123`

### Customer Self-Service Portal Login
- **URL:** http://127.0.0.1:5000/customer/login
- **Login Key:** Any registered 10-digit customer phone (e.g. `9876543210` for Asha Patel)

---

## 🧪 Running Automated Tests

Run the full suite of **52 automated unit and integration tests**:
```bash
python -m pytest -v
```

### Test Breakdown
- `tests/test_billing.py` (14 tests): Pure date-set math, 13 billing traps, leap year, holidays, rounding.
- `tests/test_transfer.py` (6 tests): Mid-cycle transfers, cycle carry-over, split pro-rated billing, pause capping, validation errors, and web routes.
- `tests/test_notifications.py` (7 tests): 9:00 AM delivery logic, holiday/weekend filtering, email rendering, SMTP dispatch logs.
- `tests/test_customer_portal.py` (6 tests): Customer login by phone, plan switching, self-service pause/resume, subscription cancellation.
- `tests/test_auth.py` (5 tests): Owner signup, login session, password hashing, logout.
- `tests/test_app.py` (6 tests): Flask routes, customer lookup, subscription freeze/unfreeze.
- `tests/test_repository.py` (3 tests): Database constraints, cascade deletes, foreign keys.
- `tests/test_validators.py` (5 tests): 10-digit Indian phone normalization, dates, pause rules.

---

## 🐛 Debugging Guide

1. **Flask Debugger:** Running with `--debug` or `FLASK_DEBUG=1` provides interactive traceback on exceptions.
2. **SQLite Database Inspection:**
   ```bash
   sqlite3 instance/tiffin.db "SELECT id, name, phone, email, start_date, end_date FROM customers;"
   sqlite3 instance/tiffin.db "SELECT * FROM subscription_transfers;"
   sqlite3 instance/tiffin.db "SELECT * FROM notification_logs ORDER BY id DESC LIMIT 5;"
   ```
3. **SMTP Connectivity Test:**
   ```bash
   python -c "import smtplib; s = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10); s.login('ssrathore.woork@gmail.com', 'ztamepzhkxjpploh'); print('SMTP OK'); s.quit()"
   ```
4. **Background Scheduler Status:** Check http://127.0.0.1:5000/notifications to view the live scheduler thread status, next scheduled 9:00 AM dispatch time, and recent dispatch logs.

---

## 📡 Complete List of API Endpoints & Routes

### 1. Public & Marketing Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/` | Luxury SaaS landing page with features, pricing, and portals | Public |

### 2. Owner Authentication Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/login` | Owner login form | Public |
| `POST` | `/login` | Process owner login credentials (`username`, `password`) | Public |
| `GET` | `/signup` | Owner signup registration form | Public |
| `POST` | `/signup` | Create owner account (`username`, `email`, `password`, `business_name`) | Public |
| `GET` | `/logout` | Sign out owner and clear session | Owner |

### 3. Customer Self-Service Portal Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/customer/login` | Customer login form (lookup by phone) | Public |
| `POST` | `/customer/login` | Authenticate customer by 10-digit phone | Public |
| `GET` | `/customer/portal` | Customer dashboard: current meal plan, live bill, pause controls | Customer Session |
| `POST` | `/customer/portal/pause` | Record customer pause (`start_date`, `end_date`, `reason`) | Customer Session |
| `POST` | `/customer/portal/resume` | Resume active pause (`resume_date`) | Customer Session |
| `POST` | `/customer/portal/change-plan` | Switch meal plan (`plan_id`) | Customer Session |
| `POST` | `/customer/portal/cancel` | Cancel customer subscription (`end_date`) | Customer Session |
| `POST` | `/customer/portal/reactivate`| Reactivate ended customer subscription | Customer Session |
| `GET` | `/customer/logout` | Log out of customer portal | Customer Session |

### 4. Owner Customer & Subscription Management
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/customers` | Full customer roster with search (`?q=`) and status filter (`?status=active\|paused\|ended`) | Owner |
| `GET` | `/customers/new` | New customer subscription form | Owner |
| `POST` | `/customers/new` | Create customer (`phone`, `name`, `email`, `address`, `plan_id`, `start_date`) | Owner |
| `GET` | `/customers/<phone>` | Customer detail view: live bill, pause history, status | Owner |
| `POST` | `/customers/<phone>/pause` | Owner records customer pause (`start_date`, `end_date`, `reason`) | Owner |
| `POST` | `/customers/<phone>/resume`| Owner resumes customer pause (`resume_date`) | Owner |
| `POST` | `/customers/<phone>/end` | End customer subscription (`end_date`) | Owner |
| `POST` | `/customers/<phone>/reactivate`| Reactivate subscription starting today | Owner |
| `POST` | `/customers/<phone>/plan` | Change customer meal plan (`plan_id`) | Owner |

### 5. Mid-Cycle Subscription Transfer Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/customers/<phone>/transfer` | Transfer form with cycle carryover & split bill preview | Owner |
| `POST` | `/customers/<phone>/transfer` | Execute transfer (`new_phone`, `new_name`, `new_email`, `new_address`, `transfer_date`, `reason`) | Owner |

### 6. Billing & Financial Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/billing` | Month-end pro-rated billing sheet (`?year=YYYY&month=MM`) | Owner |
| `POST` | `/billing/freeze` | Freeze month-end bill snapshot into persistent immutable records | Owner |
| `POST` | `/billing/unfreeze` | Unfreeze snapshot to recalculate dynamically | Owner |

### 7. Kitchen Administration Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/plans` | Meal plans list and pricing | Owner |
| `POST` | `/plans/new` | Create new meal plan (`code`, `name`, `price_rupees`) | Owner |
| `POST` | `/plans/<int:plan_id>/toggle`| Activate/deactivate a meal plan | Owner |
| `GET` | `/holidays` | Kitchen holiday closure calendar | Owner |
| `POST` | `/holidays/new` | Add scheduled service closure (`day`, `label`) | Owner |
| `POST` | `/holidays/<day>/delete` | Remove service closure | Owner |

### 8. Delivery Notifications Routes
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/notifications` | Notification dashboard, eligible subscribers today, and dispatch logs | Owner |
| `POST` | `/notifications/send-today`| Manually trigger today's 9:00 AM delivery notification batch | Owner |

---

## 🔒 Security & Data Integrity
- **Password Hashing:** Werkzeug `generate_password_hash` with PBKDF2:SHA256.
- **SQL Injection Prevention:** 100% parameterized SQLite statements via `sqlite3`.
- **Foreign Key Enforcement:** `PRAGMA foreign_keys = ON` enforced on all SQLite connections.
- **Session Protection:** Flask signed HTTP-only cookies with secret key.
- **Transaction Safety:** Transfers, bill freezing, and customer creations use atomic database commits.
