import os
import tempfile
from datetime import date
import pytest

from app import create_app
from tiffin.db import init_db
from tiffin.models import Status
from tiffin.notifications import (
    build_delivery_notification_email,
    dispatch_daily_delivery_notifications,
    get_customers_due_delivery_today,
    is_delivery_weekday,
)
from tiffin.repository import (
    add_holiday,
    create_customer,
    create_pause,
    create_plan,
    get_recent_notification_logs,
)


@pytest.fixture
def notify_app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    app = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret-notifications",
    })

    with app.app_context():
        init_db(db_path)
        p1 = create_plan("STD_LUNCH", "Standard Lunch", 300000)
        p2 = create_plan("DLX_LUNCH", "Deluxe Lunch", 380000)

        # Customer 1: Active, unpaused
        c1 = create_customer("9876543210", "Asha Patel", "Sunshine Heights", p1.id, date(2026, 9, 1), email="asha@example.com")
        # Customer 2: Paused on Sep 17
        c2 = create_customer("9988776655", "Vikram Malhotra", "Prestige Tower", p2.id, date(2026, 9, 1), email="vikram@example.com")
        create_pause(c2.id, date(2026, 9, 16), date(2026, 9, 18), "Out of town")
        # Customer 3: Ended before Sep 17
        c3 = create_customer("9812345678", "Rajesh Sharma", "Green Park", p1.id, date(2026, 8, 1), email="rajesh@example.com")
        from tiffin.repository import end_subscription
        end_subscription(c3.phone, date(2026, 9, 10))

    with app.test_client() as client:
        yield app, client, db_path

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_is_delivery_weekday():
    # 2026-09-17 is Thursday (weekday 3)
    assert is_delivery_weekday(date(2026, 9, 17)) is True
    # 2026-09-18 is Friday (weekday 4)
    assert is_delivery_weekday(date(2026, 9, 18)) is True
    # 2026-09-19 is Saturday (weekday 5)
    assert is_delivery_weekday(date(2026, 9, 19)) is False
    # 2026-09-20 is Sunday (weekday 6)
    assert is_delivery_weekday(date(2026, 9, 20)) is False


def test_weekend_has_no_delivery_notifications(notify_app):
    app, client, _ = notify_app
    with app.app_context():
        saturday = date(2026, 9, 19)
        is_delivery, reason, eligible = get_customers_due_delivery_today(saturday)
        assert is_delivery is False
        assert "weekend" in reason.lower()
        assert len(eligible) == 0


def test_holiday_has_no_delivery_notifications(notify_app):
    app, client, _ = notify_app
    with app.app_context():
        add_holiday(date(2026, 9, 25), "Festival Holiday")
        is_delivery, reason, eligible = get_customers_due_delivery_today(date(2026, 9, 25))
        assert is_delivery is False
        assert "closed" in reason.lower()
        assert len(eligible) == 0


def test_active_weekday_filters_paused_and_ended(notify_app):
    app, client, _ = notify_app
    with app.app_context():
        # Thursday 2026-09-17:
        # Asha is active & unpaused -> should be included
        # Vikram is paused Sep 16-18 -> excluded
        # Rajesh ended Sep 10 -> excluded
        thursday = date(2026, 9, 17)
        is_delivery, reason, eligible = get_customers_due_delivery_today(thursday)
        assert is_delivery is True
        assert len(eligible) == 1
        assert eligible[0].name == "Asha Patel"
        assert eligible[0].phone == "9876543210"


def test_build_delivery_notification_email(notify_app):
    app, client, _ = notify_app
    with app.app_context():
        from tiffin.repository import get_customer_by_phone
        asha = get_customer_by_phone("9876543210")
        subject, text_body, html_body = build_delivery_notification_email(asha, date(2026, 9, 17))

        assert "Lunch Delivery Today" in subject
        assert "Asha Patel" in text_body
        assert "Standard Lunch" in text_body
        assert "12:00 PM" in text_body
        assert "Asha Patel" in html_body
        assert "Sunshine Heights" in html_body


def test_dispatch_daily_delivery_notifications(notify_app):
    app, client, _ = notify_app
    with app.app_context():
        thursday = date(2026, 9, 17)
        res = dispatch_daily_delivery_notifications(on_date=thursday)
        assert res["success"] is True
        assert res["delivery_day"] is True
        assert res["sent_count"] == 1
        assert "Asha Patel" in res["customers"]

        # Check notification log created
        logs = get_recent_notification_logs(limit=10)
        assert len(logs) == 1
        assert logs[0].recipient_email == "asha@example.com"
        assert logs[0].delivery_date == thursday
        assert logs[0].status in ("logged", "sent")


def test_notifications_web_views_and_trigger(notify_app):
    app, client, _ = notify_app

    # Unauthenticated should redirect
    res_unauth = client.get("/notifications")
    assert res_unauth.status_code == 302
    assert "/login" in res_unauth.headers["Location"]

    # Log in as demo owner
    client.post("/login", data={"username": "admin", "password": "tiffin123"})

    # GET notifications view
    res_view = client.get("/notifications")
    assert res_view.status_code == 200
    assert b"Delivery Notification Service" in res_view.data
    assert b"Subscribers Due for Delivery Today" in res_view.data
    assert b"Asha Patel" in res_view.data

    # POST send-today trigger
    res_trigger = client.post("/notifications/send-today", follow_redirects=True)
    assert res_trigger.status_code == 200
    assert b"notification batch dispatched!" in res_trigger.data
