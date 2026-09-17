import os
import tempfile
from datetime import date
import pytest

from app import create_app
from tiffin.db import init_db
from tiffin.repository import (
    create_customer,
    create_plan,
    get_customer_by_phone,
    get_pauses_for_customer,
)


@pytest.fixture
def client_and_customer():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    app = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret-key-portal",
    })

    with app.app_context():
        init_db(db_path)
        # Create test plan and customer
        plan = create_plan("TEST_PLAN", "Test Lunch Plan", 250000)
        cust = create_customer("9876543210", "Asha Patel", "Sunshine Heights", plan.id, date(2026, 9, 1))

    with app.test_client() as client:
        yield client, cust, db_path

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_customer_login_flow(client_and_customer):
    client, cust, _ = client_and_customer

    # GET login page
    res = client.get("/customer/login")
    assert res.status_code == 200
    assert b"Customer Portal" in res.data

    # POST invalid phone
    res_bad = client.post("/customer/login", data={"phone": "9999999999"}, follow_redirects=True)
    assert b"No subscription found" in res_bad.data

    # POST valid phone
    res_ok = client.post("/customer/login", data={"phone": "9876543210"}, follow_redirects=True)
    assert res_ok.status_code == 200
    assert b"Welcome to your portal, Asha Patel!" in res_ok.data
    assert b"Hello, Asha Patel" in res_ok.data
    assert b"My Live Bill" in res_ok.data


def test_customer_portal_requires_login(client_and_customer):
    client, _, _ = client_and_customer
    res = client.get("/portal", follow_redirects=False)
    assert res.status_code == 302
    assert "/customer/login" in res.headers["Location"]


def test_customer_portal_pause_and_resume(client_and_customer):
    client, cust, _ = client_and_customer

    # Log in as customer
    client.post("/customer/login", data={"phone": "9876543210"})

    # Submit a pause from portal
    res_pause = client.post(
        "/portal/pause",
        data={
            "start_date": "2026-09-08",
            "end_date": "2026-09-10",
            "reason": "Family vacation",
        },
        follow_redirects=True,
    )
    assert res_pause.status_code == 200
    assert b"Tiffin delivery paused" in res_pause.data
    assert b"Family vacation" in res_pause.data

    # Submit an open-ended pause
    res_open = client.post(
        "/portal/pause",
        data={
            "start_date": "2026-09-15",
            "is_open_ended": "1",
            "reason": "Fever recovery",
        },
        follow_redirects=True,
    )
    assert res_open.status_code == 200
    assert b"Fever recovery" in res_open.data

    # Check pause in DB and resume it
    with client.application.app_context():
        pauses = get_pauses_for_customer(cust.id)
        open_pause = next(p for p in pauses if p.is_open)
        assert open_pause.reason == "Fever recovery"

    # Resume the open pause
    res_resume = client.post(
        "/portal/resume",
        data={
            "pause_id": str(open_pause.id),
            "resume_date": "2026-09-17",
        },
        follow_redirects=True,
    )
    assert res_resume.status_code == 200
    assert b"Delivery resumed!" in res_resume.data


def test_customer_portal_change_plan(client_and_customer):
    client, cust, _ = client_and_customer
    client.post("/customer/login", data={"phone": "9876543210"})

    with client.application.app_context():
        new_plan = create_plan("PREMIUM_PLAN", "Premium Deluxe Plan", 450000)

    res_change = client.post(
        "/portal/change-plan",
        data={"plan_id": str(new_plan.id)},
        follow_redirects=True,
    )
    assert res_change.status_code == 200
    assert b"Meal plan updated to" in res_change.data
    assert b"Premium Deluxe Plan" in res_change.data


def test_customer_portal_cancel_and_reactivate(client_and_customer):
    client, cust, _ = client_and_customer
    client.post("/customer/login", data={"phone": "9876543210"})

    # Cancel subscription
    res_cancel = client.post(
        "/portal/cancel",
        data={"end_date": "2026-09-20"},
        follow_redirects=True,
    )
    assert res_cancel.status_code == 200
    assert b"scheduled to end" in res_cancel.data

    with client.application.app_context():
        updated = get_customer_by_phone("9876543210")
        assert updated.end_date == date(2026, 9, 20)

    # Reactivate subscription
    res_reactivate = client.post(
        "/portal/reactivate",
        follow_redirects=True,
    )
    assert res_reactivate.status_code == 200
    assert b"Subscription reactivated!" in res_reactivate.data

    with client.application.app_context():
        reactivated = get_customer_by_phone("9876543210")
        assert reactivated.end_date is None


def test_customer_logout(client_and_customer):
    client, _, _ = client_and_customer
    client.post("/customer/login", data={"phone": "9876543210"})

    res_out = client.get("/customer/logout", follow_redirects=True)
    assert res_out.status_code == 200
    assert b"signed out of your customer portal" in res_out.data

    # Should no longer be able to access portal
    res_portal = client.get("/portal", follow_redirects=False)
    assert res_portal.status_code == 302
