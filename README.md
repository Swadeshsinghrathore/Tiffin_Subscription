# 🍱 TiffinBox — Tiffin Subscription & Pro-Rated Billing Engine

A production-ready Flask application built for home-style tiffin (lunch delivery) businesses. Customers subscribe to monthly meal plans and receive hot lunches every weekday (Mon–Fri). Subscribers pause for travel, illness, or festivals and **must not be charged for paused days**. At month-end, the owner generates transparent, mathematically exact pro-rated billing sheets.

---

## 🎯 The Core Billing Rule

```
billable_days  = delivery weekdays in month − service holidays        ← denominator (month-wide, SAME for every customer)
delivered_days = billable_days ∩ subscription window − paused dates   ← numerator (per customer)
amount         = plan_price × delivered_days / billable_days
```

### 💡 Why the Denominator is Month-Wide
If the denominator were each customer's own subscription window, a subscriber joining on the 14th of the month would pay 100% of the full monthly plan for half a month of food. By using the month's total delivery weekdays as the uniform denominator, joining mid-month pro-rates fairly against the full month's capacity.

### 🛡️ Three Mathematical Guarantees
1. **Exact Plan Price for Full Months:** When `delivered == billable`, the bill is **strictly** the plan price. Rounding never drifts a full month of ₹3,000 to ₹2,999.98.
2. **Never Touch a Float for Currency:** All prices and amounts are stored as integer **paise** (`1 Rupee = 100 paise`). Fractions are divided using Python's `Decimal` and quantized with `ROUND_HALF_UP` to whole paise.
3. **Multiply Before Dividing:** Never round the daily rate and then multiply by days delivered. Multiply `plan_price_paise * delivered_days` first, divide by `billable_days`, and round once at the end.

---

## 📅 Set Theory for Dates (`set[date]`)

Dates are modelled as sets of `datetime.date` and combined with pure set operations. A month is $\le 31$ elements, so memory and time are negligible, while classic calendar bugs vanish by construction:

- **Weekends are never in delivery sets:** Pausing Friday $\to$ Monday deducts 2 delivery days, not 4 calendar days.
- **Set union automatically deduplicates:** Overlapping pauses (e.g. 5th–10th and 8th–12th) cannot double-deduct shared days (8th–10th).
- **Clipping is natural:** A pause spanning month boundaries (e.g. Jan 28 $\to$ Feb 5) splits cleanly across January and February billing sheets.
- **Derived Status:** Customer status (`NOT_STARTED | ACTIVE | PAUSED | ENDED`) is a pure derived function `status_on(customer, pauses, on_date)`. No `is_paused` DB flag to desynchronize.

---

## 🛡️ The 13 Billing Traps & Test Suite

| # | Trap / Edge Case | Handled Behavior | Unit Test |
|---|---|---|---|
| **1** | Full month, no pause | Exactly the plan price (to the paisa) | `test_trap_1_full_month_no_pause_is_exact` |
| **2** | Pause Fri $\to$ Mon | Exactly 2 days deducted (Fri & Mon), not 4 | `test_trap_2_pause_fri_to_mon_deducts_two_days` |
| **3** | Pause only on Sat + Sun | ₹0 deducted; bill equals full plan price | `test_trap_3_pause_covering_only_sat_sun` |
| **4** | Pause Jan 28 $\to$ Feb 5 | Jan bill deducts Jan weekdays; Feb bill deducts Feb weekdays | `test_trap_4_pause_spanning_month_boundary` |
| **5** | Overlapping pauses (5–10 & 8–12) | Shared days (8–10) deducted only once | `test_trap_5_overlapping_pauses_deduplicate` |
| **6** | Open-ended pause | Clipped at month-end; earlier months unaffected | `test_trap_6_open_ended_pause_clipped_earlier_unaffected` |
| **7** | Subscribe on 14th (mid-month) | Pro-rated against month-wide denominator (~half price) | `test_trap_7_mid_month_subscribe_uses_month_wide_denominator` |
| **8** | Pause dated before start date | Only intersects with active window; never negative | `test_trap_8_pause_before_start_date_never_negative` |
| **9** | Paused all month | Exactly ₹0.00 | `test_trap_9_paused_all_month_is_zero` |
| **10** | Feb leap vs non-leap | 21 weekdays (2024 leap) vs 20 weekdays (2023 non-leap) | `test_trap_10_feb_leap_vs_non_leap` |
| **11** | Service holiday mid-month | Removed from denominator AND numerator; full month still exact | `test_trap_11_holiday_mid_month_exact_full_bill` |
| **12** | Rounding at `.005` | Integer paise quantized with `ROUND_HALF_UP` | `test_trap_12_rounding_at_half_paise` |
| **13** | Subscription ended mid-month | Billed only through `end_date` | `test_trap_13_subscription_ended_mid_month` |

---

## 🏗️ Architecture & File Layout

```
├── app.py                  # Flask application factory and HTTP routes
├── schema.sql              # DDL schema for SQLite
├── seed_demo.py            # Script to seed realistic demo data
├── requirements.txt        # Dependencies: flask, pytest
├── README.md               # Documentation and walkthrough
├── tiffin/
│   ├── __init__.py
│   ├── db.py               # SQLite connection, row factory, PRAGMA foreign_keys
│   ├── models.py           # Dataclasses: Plan, Customer, Pause, Holiday, BillLine, Status
│   ├── billing.py          # Pure date-set & Decimal math (Zero Flask/SQLite dependencies!)
│   ├── repository.py       # SQL queries for plans, subscribers, pauses, holidays, bills
│   └── validators.py       # Phone normalisation (10-digit 6-9), dates, pause/resume rules
├── templates/
│   ├── base.html           # Brand header, navigation bar, flash messages
│   ├── customers.html      # Roster with search & status filter pills (Active/Paused/Ended)
│   ├── customer_detail.html# Single customer: live month bill, pause history, pause/resume
│   ├── subscribe.html      # New subscriber signup form
│   ├── billing.html        # Month picker, itemized billing table, freeze & unfreeze
│   ├── plans.html          # Plan management and pricing
│   └── holidays.html       # Kitchen closure schedule
├── static/
│   └── style.css           # Modern design system (warm saffron palette, responsive cards)
└── tests/
    ├── test_billing.py     # Pure 13-trap edge-case suite
    ├── test_validators.py  # Phone normalization and pause rule checks
    ├── test_repository.py  # SQLite repository and FK integrity tests
    └── test_app.py         # End-to-end Flask integration tests
```

---

## 🚀 Setup & Quick Start

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Run the Full Test Suite
```bash
python -m pytest -v
```
*Expected: 28/28 tests passing (14 billing, 5 validator, 3 repository, 6 app routes).*

### 3. Seed Demo Data (Optional)
```bash
python seed_demo.py
```

### 4. Run the Web Application
```bash
python -m flask --app app run --port 5000
```
Open **`http://127.0.0.1:5000`** in your browser.

---

## 📱 Phone Normalisation Rules
Customers are keyed and looked up by their phone number. `normalize_phone` handles diverse input formats:
- `+91 98765-43210` $\to$ `9876543210`
- `09876543210` $\to$ `9876543210`
- `919876543210` $\to$ `9876543210`
- `98765 43210` $\to$ `9876543210`

Requirements: exactly 10 digits starting with **6, 7, 8, or 9**.

---

## 🔒 Live vs. Frozen Billing Sheets
- **Live Preview:** While a month is ongoing, `/billing` computes numbers dynamically in real time.
- **Freeze Invoices:** At month-end, the owner clicks **`Freeze & Finalize Bills`**. This saves a snapshot into the `bills` table with a timestamp.
- **Immutability:** Once frozen, retroactive edits to customer pauses cannot accidentally rewrite bills the owner has already collected on.
- **Unfreeze:** The owner can unfreeze anytime to allow live recalculations if adjustments are needed.
