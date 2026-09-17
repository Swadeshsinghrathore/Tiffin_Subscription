"""Seed realistic demo data for Tiffin Subscription App."""

import calendar
from datetime import date, timedelta
from tiffin.db import init_db
from tiffin.repository import (
    add_holiday,
    create_customer,
    create_pause,
    get_all_plans,
    get_customers,
)


def seed_demo_data():
    init_db()

    # Check if customers already exist
    existing = get_customers()
    if existing:
        print(f"Database already contains {len(existing)} customers. Skipping seed.")
        return

    today = date.today()
    first_of_month = date(today.year, today.month, 1)

    plans = get_all_plans()
    plan_map = {p.code: p.id for p in plans}

    print("Seeding demo subscribers...")

    # 1. Vikram Malhotra: Full unpaused month (Standard Veg ₹3,000)
    c1 = create_customer(
        phone="9988776655",
        name="Vikram Malhotra",
        address="Flat 12A, Sea Green Towers, Bandra West",
        plan_id=plan_map["STD_VEG"],
        start_date=first_of_month,
    )
    print(f"Created {c1.name} ({c1.phone}) - Unpaused full month")

    # 2. Asha Patel: Friday -> Monday pause (Deluxe Veg ₹3,800)
    c2 = create_customer(
        phone="9876543210",
        name="Asha Patel",
        address="Plot 44, Shantiniketan Colony, Andheri East",
        plan_id=plan_map["DLX_VEG"],
        start_date=first_of_month,
    )
    # Find first Friday in the month
    cur = first_of_month
    while cur.weekday() != 4:  # Friday
        cur += timedelta(days=1)
    fri_date = cur
    mon_date = cur + timedelta(days=3)  # Monday
    create_pause(c2.id, fri_date, mon_date, "Family trip to Lonavala")
    print(f"Created {c2.name} ({c2.phone}) - Paused Fri {fri_date} to Mon {mon_date}")

    # 3. Rajesh Sharma: Currently paused (Open-ended pause)
    c3 = create_customer(
        phone="9812345678",
        name="Rajesh Sharma",
        address="102 Lake View Apts, Powai",
        plan_id=plan_map["STD_VEG"],
        start_date=first_of_month,
    )
    # Pause started 2 days ago, open-ended
    pause_start = max(first_of_month, today - timedelta(days=2))
    create_pause(c3.id, pause_start, None, "Recovering from viral fever")
    print(f"Created {c3.name} ({c3.phone}) - Open-ended pause since {pause_start}")

    # 4. Priya Sundaram: Mid-month join (Mini Meal ₹2,200)
    mid_join = min(
        date(today.year, today.month, 14),
        date(today.year, today.month, calendar.monthrange(today.year, today.month)[1] - 2)
    )
    c4 = create_customer(
        phone="9712398765",
        name="Priya Sundaram",
        address="B-304 Emerald Heights, Goregaon",
        plan_id=plan_map["MINI_MEAL"],
        start_date=mid_join,
    )
    print(f"Created {c4.name} ({c4.phone}) - Joined mid-month on {mid_join}")

    # Add a service holiday in the current month
    holiday_date = min(
        date(today.year, today.month, 15),
        date(today.year, today.month, calendar.monthrange(today.year, today.month)[1] - 1)
    )
    # If it falls on weekend, shift to weekday
    while holiday_date.weekday() in (5, 6):
        holiday_date += timedelta(days=1)

    add_holiday(holiday_date, "Community Festival / Kitchen Deep Clean")
    print(f"Added service holiday on {holiday_date}")

    print("\nDemo data seeding completed successfully!")


if __name__ == "__main__":
    seed_demo_data()
