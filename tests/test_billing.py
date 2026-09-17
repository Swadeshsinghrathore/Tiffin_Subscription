from datetime import date
from decimal import Decimal
import pytest

from tiffin.billing import (
    DELIVERY_WEEKDAYS,
    compute_bill,
    delivery_days,
    month_bounds,
    paused_dates,
    prorate,
    status_on,
    subscription_days,
)
from tiffin.models import Customer, Pause, Plan, Status


@pytest.fixture
def standard_plan():
    return Plan(
        id=1,
        code="STD_VEG",
        name="Standard Veg",
        monthly_price_paise=300000,  # ₹3,000.00
        is_active=True,
    )


@pytest.fixture
def full_month_customer():
    return Customer(
        id=10,
        phone="9876543210",
        name="Asha Patel",
        address="123 Street, Mumbai",
        plan_id=1,
        start_date=date(2024, 3, 1),
        end_date=None,
    )


def test_trap_1_full_month_no_pause_is_exact(standard_plan, full_month_customer):
    """Trap 1: Full unpaused month must be exactly the plan price (to the paisa)."""
    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[],
        year=2024,
        month=3,
    )
    # March 2024 has 21 weekdays (starts Friday Mar 1, ends Sunday Mar 31)
    assert bill.billable_days == 21
    assert bill.delivered_days == 21
    assert bill.paused_days == 0
    assert bill.amount_paise == 300000
    assert bill.amount_formatted == "₹3,000.00"


def test_trap_2_pause_fri_to_mon_deducts_two_days(standard_plan, full_month_customer):
    """Trap 2: Pause Fri -> Mon deducts 2 days (Fri & Mon), not 4 calendar days."""
    # In March 2024: Mar 1 is Fri, Mar 2 Sat, Mar 3 Sun, Mar 4 Mon
    pause = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 4),
        reason="Long weekend trip",
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[pause],
        year=2024,
        month=3,
    )
    assert bill.billable_days == 21
    assert bill.paused_days == 2
    assert bill.delivered_days == 19
    # Daily rate: 300,000 / 21 = 14,285.714...
    # 19 * 300,000 / 21 = 271,428.5714... -> rounds to 271,429 paise
    assert bill.amount_paise == 271429


def test_trap_3_pause_covering_only_sat_sun(standard_plan, full_month_customer):
    """Trap 3: Pause covering only Saturday + Sunday deducts ₹0; bill equals plan price."""
    # March 2 (Sat) and March 3 (Sun), 2024
    pause = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 2),
        end_date=date(2024, 3, 3),
        reason="Weekend get-together",
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[pause],
        year=2024,
        month=3,
    )
    assert bill.billable_days == 21
    assert bill.delivered_days == 21
    assert bill.paused_days == 0
    assert bill.amount_paise == 300000


def test_trap_4_pause_spanning_month_boundary(standard_plan, full_month_customer):
    """Trap 4: Pause Jan 28 -> Feb 5 splits correctly: Jan deducts Jan weekdays, Feb deducts Feb weekdays."""
    # Jan 28 is Sun, Jan 29 Mon, Jan 30 Tue, Jan 31 Wed (3 Jan weekdays)
    # Feb 1 Thu, Feb 2 Fri, Feb 3 Sat, Feb 4 Sun, Feb 5 Mon (3 Feb weekdays)
    pause = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 1, 28),
        end_date=date(2024, 2, 5),
        reason="Family function",
    )
    customer = Customer(
        id=10,
        phone="9876543210",
        name="Asha Patel",
        address="",
        plan_id=1,
        start_date=date(2024, 1, 1),
    )

    jan_bill = compute_bill(
        plan=standard_plan,
        customer=customer,
        pauses=[pause],
        year=2024,
        month=1,
    )
    feb_bill = compute_bill(
        plan=standard_plan,
        customer=customer,
        pauses=[pause],
        year=2024,
        month=2,
    )

    # Jan 2024 has 23 weekdays
    assert jan_bill.billable_days == 23
    assert jan_bill.paused_days == 3
    assert jan_bill.delivered_days == 20

    # Feb 2024 (leap year) has 21 weekdays
    assert feb_bill.billable_days == 21
    assert feb_bill.paused_days == 3
    assert feb_bill.delivered_days == 18


def test_trap_5_overlapping_pauses_deduplicate(standard_plan, full_month_customer):
    """Trap 5: Overlapping pauses 5–10 and 8–12 deduct days 8–10 only once."""
    # March 5 (Tue) to March 10 (Sun) -> weekdays Mar 5, 6, 7, 8 (4 weekdays)
    # March 8 (Fri) to March 12 (Tue) -> weekdays Mar 8, 11, 12 (3 weekdays)
    # Combined union: Mar 5, 6, 7, 8, 11, 12 -> 6 weekdays total
    p1 = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 5),
        end_date=date(2024, 3, 10),
    )
    p2 = Pause(
        id=2,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 8),
        end_date=date(2024, 3, 12),
    )

    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[p1, p2],
        year=2024,
        month=3,
    )
    assert bill.billable_days == 21
    assert bill.paused_days == 6
    assert bill.delivered_days == 15
    # 15 * 300,000 / 21 = 214,285.714... -> 214,286 paise
    assert bill.amount_paise == 214286


def test_trap_6_open_ended_pause_clipped_earlier_unaffected(standard_plan, full_month_customer):
    """Trap 6: Open-ended pause clips at month end; earlier months remain unaffected."""
    # Open-ended pause starting March 15, 2024
    open_pause = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 15),
        end_date=None,
    )

    # February 2024 bill must be completely unaffected
    feb_customer = Customer(
        id=10,
        phone="9876543210",
        name="Asha Patel",
        address="",
        plan_id=1,
        start_date=date(2024, 2, 1),
    )
    feb_bill = compute_bill(
        plan=standard_plan,
        customer=feb_customer,
        pauses=[open_pause],
        year=2024,
        month=2,
    )
    assert feb_bill.paused_days == 0
    assert feb_bill.delivered_days == feb_bill.billable_days
    assert feb_bill.amount_paise == 300000

    # March 2024 bill: paused from March 15 to March 31
    # March 15 (Fri) to March 31 has 11 weekdays: Mar 15, 18, 19, 20, 21, 22, 25, 26, 27, 28, 29
    march_bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[open_pause],
        year=2024,
        month=3,
    )
    assert march_bill.billable_days == 21
    assert march_bill.paused_days == 11
    assert march_bill.delivered_days == 10


def test_trap_7_mid_month_subscribe_uses_month_wide_denominator(standard_plan):
    """Trap 7: Subscribe on the 14th -> ~half price, using the month-wide denominator."""
    # Customer joins March 14, 2024 (Thursday)
    mid_customer = Customer(
        id=11,
        phone="9876500000",
        name="Rahul Verma",
        address="",
        plan_id=1,
        start_date=date(2024, 3, 14),
        end_date=None,
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=mid_customer,
        pauses=[],
        year=2024,
        month=3,
    )
    # Weekdays in March from Mar 14 to Mar 31:
    # Mar 14 (Thu), Mar 15 (Fri) -> 2
    # Mar 18-22 -> 5
    # Mar 25-29 -> 5
    # Total delivered = 12 weekdays out of 21 billable weekdays
    assert bill.billable_days == 21
    assert bill.delivered_days == 12
    # 12 * 300,000 / 21 = 171,428.5714... -> 171,429 paise
    assert bill.amount_paise == 171429
    # Ensure not billed full month
    assert bill.amount_paise < standard_plan.monthly_price_paise


def test_trap_8_pause_before_start_date_never_negative(standard_plan):
    """Trap 8: Pause dated before start_date does not double-deduct and delivered is never negative."""
    # Customer subscribed starting March 18, 2024
    customer = Customer(
        id=12,
        phone="9876511111",
        name="Kavita Shah",
        address="",
        plan_id=1,
        start_date=date(2024, 3, 18),
        end_date=None,
    )
    # Pause was set from March 1 to March 22
    pause = Pause(
        id=1,
        customer_id=customer.id,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 22),
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=customer,
        pauses=[pause],
        year=2024,
        month=3,
    )
    # Total weekdays in March: 21
    # Customer active window: Mar 18 - Mar 31 -> 10 weekdays (Mar 18-22: 5, Mar 25-29: 5)
    # Paused days within window: Mar 18-22 -> 5 weekdays
    # Delivered days: Mar 25-29 -> 5 weekdays
    assert bill.billable_days == 21
    assert bill.paused_days == 5
    assert bill.delivered_days == 5
    assert bill.delivered_days >= 0
    assert bill.amount_paise == prorate(300000, 5, 21)


def test_trap_9_paused_all_month_is_zero(standard_plan, full_month_customer):
    """Trap 9: Paused all month results in ₹0 bill."""
    pause = Pause(
        id=1,
        customer_id=full_month_customer.id,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[pause],
        year=2024,
        month=3,
    )
    assert bill.billable_days == 21
    assert bill.delivered_days == 0
    assert bill.paused_days == 21
    assert bill.amount_paise == 0
    assert bill.amount_formatted == "₹0.00"


def test_trap_10_feb_leap_vs_non_leap(standard_plan):
    """Trap 10: Feb leap (2024) vs non-leap (2023) yields correct weekday counts."""
    # Feb 2024: 29 days, starts Thu Feb 1, ends Thu Feb 29 -> 21 weekdays
    b2024_lo, b2024_hi = month_bounds(2024, 2)
    days_2024 = delivery_days(b2024_lo, b2024_hi)
    assert len(days_2024) == 21

    # Feb 2023: 28 days, starts Wed Feb 1, ends Tue Feb 28 -> 20 weekdays
    b2023_lo, b2023_hi = month_bounds(2023, 2)
    days_2023 = delivery_days(b2023_lo, b2023_hi)
    assert len(days_2023) == 20


def test_trap_11_holiday_mid_month_exact_full_bill(standard_plan, full_month_customer):
    """Trap 11: Holiday removed from both numerator and denominator; full month bill is still exact."""
    # Holi on Monday March 25, 2024
    holidays = {date(2024, 3, 25)}
    bill = compute_bill(
        plan=standard_plan,
        customer=full_month_customer,
        pauses=[],
        year=2024,
        month=3,
        holidays=holidays,
    )
    # 21 weekdays - 1 holiday = 20 billable days
    assert bill.billable_days == 20
    assert bill.delivered_days == 20
    assert bill.amount_paise == 300000


def test_trap_12_rounding_at_half_paise():
    """Trap 12: Rounding at .005 uses ROUND_HALF_UP to whole paise."""
    # 1001 paise * 1 / 2 = 500.5 paise -> rounds UP to 501 paise
    assert prorate(1001, 1, 2) == 501

    # 1000 paise * 1 / 3 = 333.333... -> 333 paise
    assert prorate(1000, 1, 3) == 333

    # 2000 paise * 2 / 3 = 4000 / 3 = 1333.333... -> 1333 paise
    assert prorate(2000, 2, 3) == 1333

    # 1000 paise * 2 / 3 = 2000 / 3 = 666.666... -> 667 paise
    assert prorate(1000, 2, 3) == 667


def test_trap_13_subscription_ended_mid_month(standard_plan):
    """Trap 13: Subscription ended mid-month is billed only through end_date."""
    # Customer ends on March 15, 2024 (Friday)
    customer = Customer(
        id=13,
        phone="9876522222",
        name="Manish Joshi",
        address="",
        plan_id=1,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 15),
    )
    bill = compute_bill(
        plan=standard_plan,
        customer=customer,
        pauses=[],
        year=2024,
        month=3,
    )
    # Delivery days Mar 1 - Mar 15: 11 weekdays
    assert bill.billable_days == 21
    assert bill.delivered_days == 11
    # 11 * 300,000 / 21 = 157,142.857... -> 157,143 paise
    assert bill.amount_paise == 157143


def test_status_on_derivation():
    """Verify status_on returns NOT_STARTED, ACTIVE, PAUSED, ENDED cleanly."""
    customer = Customer(
        id=14,
        phone="9876533333",
        name="Sneha Rao",
        address="",
        plan_id=1,
        start_date=date(2024, 3, 10),
        end_date=date(2024, 3, 25),
    )
    pause = Pause(
        id=1,
        customer_id=14,
        start_date=date(2024, 3, 15),
        end_date=date(2024, 3, 18),
    )

    # Before start
    assert status_on(customer, [pause], date(2024, 3, 5)) == Status.NOT_STARTED
    # Active before pause
    assert status_on(customer, [pause], date(2024, 3, 12)) == Status.ACTIVE
    # During pause
    assert status_on(customer, [pause], date(2024, 3, 16)) == Status.PAUSED
    # Active after pause
    assert status_on(customer, [pause], date(2024, 3, 20)) == Status.ACTIVE
    # After subscription end
    assert status_on(customer, [pause], date(2024, 3, 26)) == Status.ENDED
