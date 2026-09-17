from datetime import date, datetime, timedelta
from typing import Optional
from werkzeug.security import check_password_hash, generate_password_hash

from tiffin.billing import compute_bill, status_on
from tiffin.db import get_db
from tiffin.models import (
    BillLine,
    Customer,
    Holiday,
    NotificationLog,
    Owner,
    Pause,
    Plan,
    Status,
    SubscriptionTransfer,
)
from tiffin.validators import ValidationError, normalize_phone


def _row_to_plan(row) -> Plan:
    return Plan(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        monthly_price_paise=row["monthly_price_paise"],
        is_active=bool(row["is_active"]),
    )


def _row_to_pause(row) -> Pause:
    return Pause(
        id=row["id"],
        customer_id=row["customer_id"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]) if row["end_date"] else None,
        reason=row["reason"],
        created_at=row["created_at"],
    )


def _row_to_customer(row, plan: Optional[Plan] = None) -> Customer:
    keys = row.keys() if hasattr(row, "keys") else []
    return Customer(
        id=row["id"],
        phone=row["phone"],
        name=row["name"],
        address=row["address"],
        email=row["email"] if "email" in keys else None,
        plan_id=row["plan_id"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]) if row["end_date"] else None,
        created_at=row["created_at"],
        plan=plan,
    )


# --- Plans Repository ---

def get_all_plans(include_inactive: bool = True) -> list[Plan]:
    conn = get_db()
    sql = "SELECT * FROM plans"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY monthly_price_paise ASC"
    rows = conn.execute(sql).fetchall()
    return [_row_to_plan(r) for r in rows]


def get_plan_by_id(plan_id: int) -> Optional[Plan]:
    conn = get_db()
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return _row_to_plan(row) if row else None


def get_plan_by_code(code: str) -> Optional[Plan]:
    conn = get_db()
    row = conn.execute("SELECT * FROM plans WHERE code = ?", (code,)).fetchone()
    return _row_to_plan(row) if row else None


def create_plan(code: str, name: str, monthly_price_paise: int) -> Plan:
    conn = get_db()
    clean_code = code.strip().upper()
    existing = get_plan_by_code(clean_code)
    if existing:
        raise ValidationError(f"Plan code '{clean_code}' already exists.")
    cur = conn.execute(
        "INSERT INTO plans (code, name, monthly_price_paise, is_active) VALUES (?, ?, ?, 1)",
        (clean_code, name.strip(), monthly_price_paise),
    )
    conn.commit()
    return get_plan_by_id(cur.lastrowid)  # type: ignore


def toggle_plan_active(plan_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE plans SET is_active = 1 - is_active WHERE id = ?", (plan_id,))
    conn.commit()


# --- Customers Repository ---

def create_customer(
    phone: str,
    name: str,
    address: Optional[str],
    plan_id: int,
    start_date: date,
    email: Optional[str] = None,
) -> Customer:
    norm_phone = normalize_phone(phone)
    conn = get_db()

    # Check phone uniqueness
    existing = conn.execute("SELECT id FROM customers WHERE phone = ?", (norm_phone,)).fetchone()
    if existing:
        raise ValidationError(f"Customer with phone number {norm_phone} already exists.")

    plan = get_plan_by_id(plan_id)
    if not plan:
        raise ValidationError(f"Plan with ID {plan_id} does not exist.")

    now_iso = datetime.now().isoformat(timespec="seconds")
    clean_email = email.strip() if email and email.strip() else None
    cur = conn.execute(
        """
        INSERT INTO customers (phone, name, email, address, plan_id, start_date, end_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (norm_phone, name.strip(), clean_email, address.strip() if address else None, plan_id, start_date.isoformat(), now_iso),
    )
    conn.commit()
    return get_customer_by_id(cur.lastrowid)  # type: ignore


def get_customer_by_phone(phone: str) -> Optional[Customer]:
    try:
        norm_phone = normalize_phone(phone)
    except ValidationError:
        return None

    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE phone = ?", (norm_phone,)).fetchone()
    if not row:
        return None

    plan = get_plan_by_id(row["plan_id"])
    customer = _row_to_customer(row, plan)
    pauses = get_pauses_for_customer(customer.id)  # type: ignore
    customer.status = status_on(customer, pauses, date.today())
    customer.active_pause = get_open_pause_for_customer(customer.id)  # type: ignore
    customer.transferred_to = get_transfer_out(customer.id)  # type: ignore
    customer.transferred_from = get_transfer_in(customer.id)  # type: ignore
    return customer


def get_customer_by_id(customer_id: int) -> Optional[Customer]:
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        return None
    plan = get_plan_by_id(row["plan_id"])
    customer = _row_to_customer(row, plan)
    pauses = get_pauses_for_customer(customer.id)  # type: ignore
    customer.status = status_on(customer, pauses, date.today())
    customer.active_pause = get_open_pause_for_customer(customer.id)  # type: ignore
    customer.transferred_to = get_transfer_out(customer.id)  # type: ignore
    customer.transferred_from = get_transfer_in(customer.id)  # type: ignore
    return customer


def get_customers(
    status_filter: Optional[str] = None,
    query: Optional[str] = None,
    on_date: Optional[date] = None,
) -> list[Customer]:
    """List all customers with derived status, optional status filter, and phone/name search."""
    check_date = on_date or date.today()
    conn = get_db()

    rows = conn.execute(
        """
        SELECT c.*, p.code as plan_code, p.name as plan_name, p.monthly_price_paise as plan_price, p.is_active as plan_active
        FROM customers c
        JOIN plans p ON c.plan_id = p.id
        ORDER BY c.name ASC
        """
    ).fetchall()

    result: list[Customer] = []
    clean_q = query.strip().lower() if query else None
    # If query is digits, normalize what we can
    digits_q = "".join(filter(str.isdigit, clean_q)) if clean_q else None

    for r in rows:
        plan = Plan(
            id=r["plan_id"],
            code=r["plan_code"],
            name=r["plan_name"],
            monthly_price_paise=r["plan_price"],
            is_active=bool(r["plan_active"]),
        )
        cust = _row_to_customer(r, plan)
        pauses = get_pauses_for_customer(cust.id)  # type: ignore
        cust.status = status_on(cust, pauses, check_date)
        cust.active_pause = get_open_pause_for_customer(cust.id)  # type: ignore

        # Apply search query
        if clean_q:
            matches_name = clean_q in cust.name.lower()
            matches_phone = (digits_q and digits_q in cust.phone) or (clean_q in cust.phone)
            if not (matches_name or matches_phone):
                continue

        # Apply status filter
        if status_filter and status_filter.lower() != "all":
            if cust.status.value != status_filter.lower():
                continue

        result.append(cust)

    return result


def end_subscription(phone: str, end_date: date) -> None:
    norm_phone = normalize_phone(phone)
    conn = get_db()
    conn.execute(
        "UPDATE customers SET end_date = ? WHERE phone = ?",
        (end_date.isoformat(), norm_phone),
    )
    conn.commit()


def reactivate_subscription(phone: str) -> None:
    """Clear end_date so a previously cancelled subscription is reactivated."""
    norm_phone = normalize_phone(phone)
    conn = get_db()
    conn.execute(
        "UPDATE customers SET end_date = NULL WHERE phone = ?",
        (norm_phone,),
    )
    conn.commit()


def update_customer_plan(customer_id: int, new_plan_id: int) -> None:
    """Update a customer's meal plan to a new active plan."""
    plan = get_plan_by_id(new_plan_id)
    if not plan:
        raise ValidationError(f"Plan with ID {new_plan_id} not found.")
    if not plan.is_active:
        raise ValidationError(f"Plan '{plan.name}' is currently inactive.")
    conn = get_db()
    conn.execute(
        "UPDATE customers SET plan_id = ? WHERE id = ?",
        (new_plan_id, customer_id),
    )
    conn.commit()



# --- Pauses Repository ---

def get_pauses_for_customer(customer_id: int) -> list[Pause]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pauses WHERE customer_id = ? ORDER BY start_date DESC",
        (customer_id,),
    ).fetchall()
    return [_row_to_pause(r) for r in rows]


def get_open_pause_for_customer(customer_id: int) -> Optional[Pause]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pauses WHERE customer_id = ? AND end_date IS NULL ORDER BY start_date DESC LIMIT 1",
        (customer_id,),
    ).fetchone()
    return _row_to_pause(row) if row else None


def create_pause(
    customer_id: int,
    start_date: date,
    end_date: Optional[date] = None,
    reason: Optional[str] = None,
) -> Pause:
    conn = get_db()
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO pauses (customer_id, start_date, end_date, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            customer_id,
            start_date.isoformat(),
            end_date.isoformat() if end_date else None,
            reason.strip() if reason else None,
            now_iso,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM pauses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_pause(row)


def resume_pause(pause_id: int, end_date: date) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE pauses SET end_date = ? WHERE id = ?",
        (end_date.isoformat(), pause_id),
    )
    conn.commit()


def delete_pause(pause_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM pauses WHERE id = ?", (pause_id,))
    conn.commit()


# --- Holidays Repository ---

def get_holidays() -> list[Holiday]:
    conn = get_db()
    rows = conn.execute("SELECT day, label FROM holidays ORDER BY day ASC").fetchall()
    return [Holiday(day=date.fromisoformat(r["day"]), label=r["label"]) for r in rows]


def get_holiday_dates() -> set[date]:
    holidays = get_holidays()
    return {h.day for h in holidays}


def add_holiday(day: date, label: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO holidays (day, label) VALUES (?, ?)",
        (day.isoformat(), label.strip()),
    )
    conn.commit()


def delete_holiday(day: date) -> None:
    conn = get_db()
    conn.execute("DELETE FROM holidays WHERE day = ?", (day.isoformat(),))
    conn.commit()


# --- Bills Repository ---

def has_frozen_bills(year: int, month: int) -> bool:
    conn = get_db()
    cur = conn.execute(
        "SELECT COUNT(*) FROM bills WHERE year = ? AND month = ?",
        (year, month),
    )
    return cur.fetchone()[0] > 0


def get_frozen_bills_for_month(year: int, month: int) -> list[BillLine]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT b.*, c.phone, c.name as customer_name, c.address, c.start_date, c.end_date,
               p.id as plan_id, p.code as plan_code, p.name as plan_name, p.monthly_price_paise, p.is_active
        FROM bills b
        JOIN customers c ON b.customer_id = c.id
        JOIN plans p ON c.plan_id = p.id
        WHERE b.year = ? AND b.month = ?
        ORDER BY c.name ASC
        """,
        (year, month),
    ).fetchall()

    result: list[BillLine] = []
    for r in rows:
        plan = Plan(
            id=r["plan_id"],
            code=r["plan_code"],
            name=r["plan_name"],
            monthly_price_paise=r["monthly_price_paise"],
            is_active=bool(r["is_active"]),
        )
        customer = Customer(
            id=r["customer_id"],
            phone=r["phone"],
            name=r["customer_name"],
            address=r["address"],
            plan_id=r["plan_id"],
            start_date=date.fromisoformat(r["start_date"]),
            end_date=date.fromisoformat(r["end_date"]) if r["end_date"] else None,
            plan=plan,
        )
        bill_line = BillLine(
            customer=customer,
            plan=plan,
            year=r["year"],
            month=r["month"],
            plan_price_paise=r["plan_price_paise"],
            billable_days=r["billable_days"],
            delivered_days=r["delivered_days"],
            paused_days=r["paused_days"],
            amount_paise=r["amount_paise"],
            is_frozen=True,
            generated_at=r["generated_at"],
        )
        result.append(bill_line)

    return result


def freeze_bills(bills: list[BillLine]) -> None:
    conn = get_db()
    now_iso = datetime.now().isoformat(timespec="seconds")
    records = [
        (
            b.customer.id,
            b.year,
            b.month,
            b.plan_price_paise,
            b.billable_days,
            b.delivered_days,
            b.paused_days,
            b.amount_paise,
            now_iso,
        )
        for b in bills
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO bills (
            customer_id, year, month, plan_price_paise,
            billable_days, delivered_days, paused_days,
            amount_paise, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    conn.commit()


def unfreeze_bills(year: int, month: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM bills WHERE year = ? AND month = ?", (year, month))
    conn.commit()


# --- Owner / Auth Repository ---

def _row_to_owner(row) -> Owner:
    return Owner(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        business_name=row["business_name"],
        created_at=row["created_at"],
    )


def create_owner(
    username: str,
    email: str,
    password: str,
    business_name: str,
) -> Owner:
    conn = get_db()
    clean_u = username.strip().lower()
    clean_e = email.strip().lower()
    clean_b = business_name.strip()

    if not clean_u or not clean_e or not password:
        raise ValidationError("Username, email, and password are required.")

    # Check for existing
    existing = conn.execute(
        "SELECT id FROM owners WHERE username = ? OR email = ?",
        (clean_u, clean_e),
    ).fetchone()
    if existing:
        raise ValidationError("An owner account with this username or email already exists.")

    password_hash = generate_password_hash(password)
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO owners (username, email, password_hash, business_name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clean_u, clean_e, password_hash, clean_b or "My Tiffin Kitchen", now_iso),
    )
    conn.commit()
    return get_owner_by_id(cur.lastrowid)  # type: ignore


def get_owner_by_username_or_email(identifier: str) -> Optional[Owner]:
    conn = get_db()
    clean_id = identifier.strip().lower()
    row = conn.execute(
        "SELECT * FROM owners WHERE username = ? OR email = ?",
        (clean_id, clean_id),
    ).fetchone()
    return _row_to_owner(row) if row else None


def get_owner_by_id(owner_id: int) -> Optional[Owner]:
    conn = get_db()
    row = conn.execute("SELECT * FROM owners WHERE id = ?", (owner_id,)).fetchone()
    return _row_to_owner(row) if row else None


def verify_owner_password(owner: Owner, plain_password: str) -> bool:
    return check_password_hash(owner.password_hash, plain_password)


# --- Notification Logs Repository ---

def create_notification_log(
    customer_id: int,
    recipient_email: str,
    subject: str,
    delivery_date: date,
    status: str,
    details: Optional[str] = None,
) -> int:
    conn = get_db()
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO notification_logs (customer_id, recipient_email, subject, delivery_date, status, details, sent_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (customer_id, recipient_email.strip(), subject, delivery_date.isoformat(), status, details, now_iso),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore


def get_recent_notification_logs(limit: int = 50) -> list[NotificationLog]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT n.*, c.name as customer_name
        FROM notification_logs n
        JOIN customers c ON n.customer_id = c.id
        ORDER BY n.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        NotificationLog(
            id=r["id"],
            customer_id=r["customer_id"],
            recipient_email=r["recipient_email"],
            subject=r["subject"],
            delivery_date=date.fromisoformat(r["delivery_date"]),
            status=r["status"],
            details=r["details"],
            sent_at=r["sent_at"],
            customer_name=r["customer_name"],
        )
        for r in rows
    ]


# --- Subscription Transfers Repository ---

def _row_to_transfer(row) -> SubscriptionTransfer:
    keys = row.keys() if hasattr(row, "keys") else []
    return SubscriptionTransfer(
        id=row["id"],
        from_customer_id=row["from_customer_id"],
        to_customer_id=row["to_customer_id"],
        transfer_date=date.fromisoformat(row["transfer_date"]),
        plan_id=row["plan_id"],
        reason=row["reason"],
        created_at=row["created_at"],
        from_customer_name=row["from_customer_name"] if "from_customer_name" in keys else None,
        from_customer_phone=row["from_customer_phone"] if "from_customer_phone" in keys else None,
        to_customer_name=row["to_customer_name"] if "to_customer_name" in keys else None,
        to_customer_phone=row["to_customer_phone"] if "to_customer_phone" in keys else None,
        plan_name=row["plan_name"] if "plan_name" in keys else None,
    )


def get_transfer_out(customer_id: int) -> Optional[SubscriptionTransfer]:
    """Get the transfer record where this customer transferred their subscription to someone else."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT t.*,
               c1.name as from_customer_name, c1.phone as from_customer_phone,
               c2.name as to_customer_name, c2.phone as to_customer_phone,
               p.name as plan_name
        FROM subscription_transfers t
        JOIN customers c1 ON t.from_customer_id = c1.id
        JOIN customers c2 ON t.to_customer_id = c2.id
        JOIN plans p ON t.plan_id = p.id
        WHERE t.from_customer_id = ?
        ORDER BY t.id DESC
        LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_transfer(row)


def get_transfer_in(customer_id: int) -> Optional[SubscriptionTransfer]:
    """Get the transfer record where this customer took over a subscription from someone else."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT t.*,
               c1.name as from_customer_name, c1.phone as from_customer_phone,
               c2.name as to_customer_name, c2.phone as to_customer_phone,
               p.name as plan_name
        FROM subscription_transfers t
        JOIN customers c1 ON t.from_customer_id = c1.id
        JOIN customers c2 ON t.to_customer_id = c2.id
        JOIN plans p ON t.plan_id = p.id
        WHERE t.to_customer_id = ?
        ORDER BY t.id DESC
        LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_transfer(row)


def get_transfers_map() -> dict[int, SubscriptionTransfer]:
    """Return a mapping of customer_id -> SubscriptionTransfer for any customer involved in a transfer."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT t.*,
               c1.name as from_customer_name, c1.phone as from_customer_phone,
               c2.name as to_customer_name, c2.phone as to_customer_phone,
               p.name as plan_name
        FROM subscription_transfers t
        JOIN customers c1 ON t.from_customer_id = c1.id
        JOIN customers c2 ON t.to_customer_id = c2.id
        JOIN plans p ON t.plan_id = p.id
        """
    ).fetchall()
    result: dict[int, SubscriptionTransfer] = {}
    for r in rows:
        t = _row_to_transfer(r)
        result[t.from_customer_id] = t
        result[t.to_customer_id] = t
    return result


def transfer_subscription(
    from_customer: Customer,
    new_phone: str,
    new_name: str,
    transfer_date: date,
    new_address: Optional[str] = None,
    new_email: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[Customer, SubscriptionTransfer]:
    """
    Transfer an active subscription mid-cycle to a new customer.
    - Outgoing customer end date is set to transfer_date - 1 day.
    - Any pauses for outgoing customer starting before transfer_date are capped at transfer_date - 1 day.
    - Future pauses starting >= transfer_date are removed.
    - New customer is created with inherited plan, start_date = transfer_date, and carried-over end_date.
    - An audit transfer record is created linking from_customer -> new_customer.
    """
    if from_customer.id is None:
        raise ValidationError("Outgoing customer ID cannot be None.")

    if transfer_date <= from_customer.start_date:
        raise ValidationError(
            f"Transfer date ({transfer_date}) must be after customer start date ({from_customer.start_date})."
        )

    if from_customer.end_date is not None and transfer_date > from_customer.end_date:
        raise ValidationError(
            f"Transfer date ({transfer_date}) cannot be after customer subscription end date ({from_customer.end_date})."
        )

    norm_new_phone = normalize_phone(new_phone)
    if norm_new_phone == from_customer.phone:
        raise ValidationError("New customer phone must be different from current customer phone.")

    conn = get_db()
    existing = conn.execute("SELECT id FROM customers WHERE phone = ?", (norm_new_phone,)).fetchone()
    if existing:
        raise ValidationError(f"A customer with phone {norm_new_phone} already exists.")

    cutoff_date = transfer_date - timedelta(days=1)
    carried_end_date = from_customer.end_date
    now_iso = datetime.now().isoformat(timespec="seconds")

    # 1. Update outgoing customer's end date
    conn.execute(
        "UPDATE customers SET end_date = ? WHERE id = ?",
        (cutoff_date.isoformat(), from_customer.id),
    )

    # 2. Adjust active pauses for outgoing customer
    conn.execute(
        "DELETE FROM pauses WHERE customer_id = ? AND start_date > ?",
        (from_customer.id, cutoff_date.isoformat()),
    )
    pauses = conn.execute(
        "SELECT id, start_date, end_date FROM pauses WHERE customer_id = ? AND (end_date IS NULL OR end_date > ?)",
        (from_customer.id, cutoff_date.isoformat()),
    ).fetchall()
    for p in pauses:
        conn.execute(
            "UPDATE pauses SET end_date = ? WHERE id = ?",
            (cutoff_date.isoformat(), p["id"]),
        )

    # 3. Create incoming customer
    clean_email = new_email.strip() if new_email and new_email.strip() else f"customer_{norm_new_phone}@tiffinbox.local"
    cur = conn.execute(
        """
        INSERT INTO customers (phone, name, email, address, plan_id, start_date, end_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            norm_new_phone,
            new_name.strip(),
            clean_email,
            new_address.strip() if new_address else None,
            from_customer.plan_id,
            transfer_date.isoformat(),
            carried_end_date.isoformat() if carried_end_date else None,
            now_iso,
        ),
    )
    new_customer_id = cur.lastrowid

    # 4. Record transfer
    cur_t = conn.execute(
        """
        INSERT INTO subscription_transfers (from_customer_id, to_customer_id, transfer_date, plan_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            from_customer.id,
            new_customer_id,
            transfer_date.isoformat(),
            from_customer.plan_id,
            reason.strip() if reason else None,
            now_iso,
        ),
    )
    transfer_id = cur_t.lastrowid
    conn.commit()

    new_customer = get_customer_by_id(new_customer_id)  # type: ignore
    transfer_record = SubscriptionTransfer(
        id=transfer_id,
        from_customer_id=from_customer.id,
        to_customer_id=new_customer_id,  # type: ignore
        transfer_date=transfer_date,
        plan_id=from_customer.plan_id,
        reason=reason.strip() if reason else None,
        created_at=now_iso,
        from_customer_name=from_customer.name,
        from_customer_phone=from_customer.phone,
        to_customer_name=new_name.strip(),
        to_customer_phone=norm_new_phone,
        plan_name=from_customer.plan.name if from_customer.plan else None,
    )
    return new_customer, transfer_record  # type: ignore



