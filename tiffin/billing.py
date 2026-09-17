import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from tiffin.models import BillLine, Customer, Pause, Plan, Status

# Mon..Fri; single point of change
DELIVERY_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return the first and last dates of a given month."""
    _, num_days = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, num_days)


def delivery_days(start: date, end: date, holidays: Optional[set[date]] = None) -> set[date]:
    """Return all delivery weekdays in [start, end] minus service holidays."""
    if start > end:
        return set()
    holidays_set = holidays if holidays is not None else set()
    result: set[date] = set()
    current = start
    one_day = timedelta(days=1)
    while current <= end:
        if current.weekday() in DELIVERY_WEEKDAYS and current not in holidays_set:
            result.add(current)
        current += one_day
    return result


def subscription_days(
    customer_start: date,
    customer_end: Optional[date],
    lo: date,
    hi: date,
) -> set[date]:
    """Return the set of all calendar days in [customer_start, customer_end] clipped to [lo, hi]."""
    actual_start = max(customer_start, lo)
    actual_end = min(customer_end, hi) if customer_end is not None else hi
    if actual_start > actual_end:
        return set()

    result: set[date] = set()
    current = actual_start
    one_day = timedelta(days=1)
    while current <= actual_end:
        result.add(current)
        current += one_day
    return result


def paused_dates(pauses: Iterable[Pause], lo: date, hi: date) -> set[date]:
    """Return the union of all paused dates in [lo, hi]. Overlaps are deduplicated automatically."""
    result: set[date] = set()
    one_day = timedelta(days=1)
    for p in pauses:
        effective_start = max(p.start_date, lo)
        effective_end = min(p.end_date, hi) if p.end_date is not None else hi
        if effective_start <= effective_end:
            current = effective_start
            while current <= effective_end:
                result.add(current)
                current += one_day
    return result


def status_on(customer: Customer, pauses: Iterable[Pause], on_date: date) -> Status:
    """Derive customer status for a given date as a pure function."""
    if on_date < customer.start_date:
        return Status.NOT_STARTED

    if customer.end_date is not None and on_date > customer.end_date:
        return Status.ENDED

    for p in pauses:
        if p.end_date is None:
            if on_date >= p.start_date:
                return Status.PAUSED
        else:
            if p.start_date <= on_date <= p.end_date:
                return Status.PAUSED

    return Status.ACTIVE


def prorate(plan_price_paise: int, delivered: int, billable: int) -> int:
    """
    Prorate monthly plan price to delivered days.
    Guarantees:
      1. delivered == billable -> exact plan price (special-cased).
      2. Integer paise, Decimal division, ROUND_HALF_UP.
      3. Multiply before dividing, round once at the end.
    """
    if billable <= 0 or delivered <= 0:
        return 0
    if delivered >= billable:
        return plan_price_paise

    amount = (Decimal(plan_price_paise) * Decimal(delivered)) / Decimal(billable)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_bill(
    plan: Plan,
    customer: Customer,
    pauses: Iterable[Pause],
    year: int,
    month: int,
    holidays: Optional[set[date]] = None,
) -> BillLine:
    """
    Compute a customer's bill for a specific month.
      billable_days  = delivery weekdays in month - service holidays (denominator, month-wide)
      delivered_days = billable_days ∩ subscription window - paused dates (numerator, per customer)
      amount         = plan_price × delivered_days / billable_days
    """
    first_date, last_date = month_bounds(year, month)
    holidays_set = holidays if holidays is not None else set()

    billable_set = delivery_days(first_date, last_date, holidays_set)
    sub_set = subscription_days(customer.start_date, customer.end_date, first_date, last_date)
    pause_set = paused_dates(pauses, first_date, last_date)

    billable_count = len(billable_set)
    delivered_set = (billable_set & sub_set) - pause_set
    delivered_count = len(delivered_set)
    paused_count = len((billable_set & sub_set) & pause_set)

    amount = prorate(plan.monthly_price_paise, delivered_count, billable_count)

    return BillLine(
        customer=customer,
        plan=plan,
        year=year,
        month=month,
        plan_price_paise=plan.monthly_price_paise,
        billable_days=billable_count,
        delivered_days=delivered_count,
        paused_days=paused_count,
        amount_paise=amount,
        is_frozen=False,
        generated_at=None,
    )


def format_rupees(paise: int) -> str:
    """Format paise into INR currency representation (e.g. ₹2,454.55)."""
    return f"₹{paise / 100:,.2f}"
