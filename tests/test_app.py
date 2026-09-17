import os
import tempfile
from datetime import date
import pytest

from app import create_app
from tiffin.db import init_db


@pytest.fixture
def app_client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    app = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret-key",
    })

    with app.test_client() as client:
        with app.app_context():
            init_db(db_path)
        # Log in as demo admin by default for app client operations
        client.post(
            "/login",
            data={"username": "admin", "password": "tiffin123"},
            follow_redirects=True,
        )
        yield client

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_landing_page(app_client):
    response = app_client.get("/")
    assert response.status_code == 200
    assert b"TiffinBox" in response.data


def test_customers_roster_empty(app_client):
    response = app_client.get("/customers")
    assert response.status_code == 200
    assert b"Subscriber Roster" in response.data


def test_subscribe_and_lookup_flow(app_client):
    # GET subscribe form
    res_get = app_client.get("/customers/new")
    assert res_get.status_code == 200
    assert b"New Customer Subscription" in res_get.data

    # POST new customer
    res_post = app_client.post(
        "/customers/new",
        data={
            "phone": "+91 98765 43210",
            "name": "Asha Patel",
            "address": "402 Palm Court",
            "plan_id": "1",
            "start_date": "2024-03-01",
        },
        follow_redirects=True,
    )
    assert res_post.status_code == 200
    assert b"Asha Patel" in res_post.data
    assert b"9876543210" in res_post.data
    assert b"Standard Veg" in res_post.data

    # Test lookup via normalized phone
    res_detail = app_client.get("/customers/9876543210")
    assert res_detail.status_code == 200
    assert b"Live Bill Calculation" in res_detail.data


def test_pause_and_resume_flow(app_client):
    # Subscribe customer
    app_client.post(
        "/customers/new",
        data={
            "phone": "9876543210",
            "name": "Asha Patel",
            "address": "",
            "plan_id": "1",
            "start_date": "2024-03-01",
        },
    )

    # Pause customer
    res_pause = app_client.post(
        "/customers/9876543210/pause",
        data={
            "start_date": "2024-03-10",
            "end_date": "",
            "reason": "Traveling to hometown",
        },
        follow_redirects=True,
    )
    assert res_pause.status_code == 200
    assert b"Delivery Currently Paused" in res_pause.data
    assert b"Traveling to hometown" in res_pause.data

    # Resume delivery
    res_resume = app_client.post(
        "/customers/9876543210/resume",
        data={
            "resume_date": "2024-03-15",
        },
        follow_redirects=True,
    )
    assert res_resume.status_code == 200
    assert b"Resumed delivery for Asha Patel" in res_resume.data


def test_billing_sheet_and_freeze(app_client):
    # Subscribe customer starting Mar 1, 2024
    app_client.post(
        "/customers/new",
        data={
            "phone": "9876543210",
            "name": "Asha Patel",
            "address": "",
            "plan_id": "1",
            "start_date": "2024-03-01",
        },
    )

    # View billing for March 2024
    res_bill = app_client.get("/billing?year=2024&month=3")
    assert res_bill.status_code == 200
    assert b"March 2024" in res_bill.data
    assert b"Live Calculation" in res_bill.data
    assert b"3,000.00" in res_bill.data

    # Freeze bills
    res_freeze = app_client.post(
        "/billing/generate",
        data={"year": "2024", "month": "3"},
        follow_redirects=True,
    )
    assert res_freeze.status_code == 200
    assert b"Frozen Invoices" in res_freeze.data
    assert b"Frozen Snapshot" in res_freeze.data

    # Unfreeze bills
    res_unfreeze = app_client.post(
        "/billing/unfreeze",
        data={"year": "2024", "month": "3"},
        follow_redirects=True,
    )
    assert res_unfreeze.status_code == 200
    assert b"Live Calculation" in res_unfreeze.data


def test_plans_and_holidays(app_client):
    # Create new plan
    res_plan = app_client.post(
        "/plans",
        data={
            "code": "SPECIAL_JAIN",
            "name": "Special Jain Meal",
            "price_rupees": "3500",
        },
        follow_redirects=True,
    )
    assert res_plan.status_code == 200
    assert b"SPECIAL_JAIN" in res_plan.data

    # Add holiday
    res_holiday = app_client.post(
        "/holidays",
        data={
            "day": "2024-03-25",
            "label": "Holi Festival",
        },
        follow_redirects=True,
    )
    assert res_holiday.status_code == 200
    assert b"Holi Festival" in res_holiday.data
