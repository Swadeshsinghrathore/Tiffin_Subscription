import os
import tempfile
from datetime import date
import pytest

from app import create_app
from tiffin.billing import compute_bill
from tiffin.db import init_db
from tiffin.models import Status
from tiffin.repository import (
    create_customer,
    create_pause,
    create_plan,
    get_customer_by_phone,
    get_frozen_bills_for_month,
    get_pauses_for_customer,
    get_transfer_in,
    get_transfer_out,
    transfer_subscription,
)
from tiffin.validators import ValidationError, validate_transfer


@pytest.fixture
def transfer_app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    app = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret-transfer",
    })

    with app.app_context():
        init_db(db_path)
        # Create standard plan: ₹3,000 / month
        p1 = create_plan("STD_LUNCH", "Standard Lunch", 300000)
        # Create deluxe plan: ₹3,800 / month
        p2 = create_plan("DLX_LUNCH", "Deluxe Lunch", 380000)

        # Create active customer for September 2026 (Sep 1 to Sep 30)
        c1 = create_customer(
            phone="9876543210",
            name="Amit Verma",
            address="Flat 402, Lotus Residency",
            plan_id=p2.id,
            start_date=date(2026, 9, 1),
            email="amit@example.com",
        )

    with app.test_client() as client:
        yield app, client, db_path

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_transfer_subscription_cycle_carryover(transfer_app):
    app, _, _ = transfer_app
    with app.app_context():
        amit = get_customer_by_phone("9876543210")
        assert amit is not None

        # Transfer mid-cycle on September 16, 2026
        transfer_d = date(2026, 9, 16)
        new_cust, record = transfer_subscription(
            from_customer=amit,
            new_phone="9812345678",
            new_name="Priya Nair",
            transfer_date=transfer_d,
            new_address="Flat 402, Lotus Residency",
            new_email="priya@example.com",
            reason="Roommate flat takeover",
        )

        # Check incoming customer properties
        assert new_cust.phone == "9812345678"
        assert new_cust.name == "Priya Nair"
        assert new_cust.email == "priya@example.com"
        assert new_cust.plan_id == amit.plan_id  # Plan carries over
        assert new_cust.start_date == transfer_d  # Starts on transfer date
        assert new_cust.status == Status.ACTIVE

        # Check outgoing customer properties
        amit_updated = get_customer_by_phone("9876543210")
        assert amit_updated.end_date == date(2026, 9, 15)  # Ends on day before transfer

        # Check transfer audit record
        assert record.from_customer_id == amit.id
        assert record.to_customer_id == new_cust.id
        assert record.transfer_date == transfer_d
        assert record.reason == "Roommate flat takeover"

        # Check bidirectional links
        t_out = get_transfer_out(amit.id)
        assert t_out is not None
        assert t_out.to_customer_name == "Priya Nair"

        t_in = get_transfer_in(new_cust.id)
        assert t_in is not None
        assert t_in.from_customer_name == "Amit Verma"


def test_transfer_splits_billing_exact_paise(transfer_app):
    app, _, _ = transfer_app
    with app.app_context():
        amit = get_customer_by_phone("9876543210")
        # September 2026 has 22 weekdays.
        # Transfer on Sep 16 (Wednesday):
        # Sep 1..15 = 11 weekdays (Tue Sep 1 to Tue Sep 15)
        # Sep 16..30 = 11 weekdays (Wed Sep 16 to Wed Sep 30)
        transfer_d = date(2026, 9, 16)
        priya, _ = transfer_subscription(
            from_customer=amit,
            new_phone="9812345678",
            new_name="Priya Nair",
            transfer_date=transfer_d,
        )

        amit_updated = get_customer_by_phone("9876543210")

        # Compute bill for Amit (Sep 1 to Sep 15)
        pauses_amit = get_pauses_for_customer(amit_updated.id)
        bill_amit = compute_bill(
            plan=amit_updated.plan,
            customer=amit_updated,
            pauses=pauses_amit,
            year=2026,
            month=9,
        )

        # Compute bill for Priya (Sep 16 to Sep 30)
        pauses_priya = get_pauses_for_customer(priya.id)
        bill_priya = compute_bill(
            plan=priya.plan,
            customer=priya,
            pauses=pauses_priya,
            year=2026,
            month=9,
        )

        assert bill_amit.billable_days == 22
        assert bill_priya.billable_days == 22

        # 11 weekdays each
        assert bill_amit.delivered_days == 11
        assert bill_priya.delivered_days == 11

        # Sum of delivered days equals total delivery days
        assert bill_amit.delivered_days + bill_priya.delivered_days == 22

        # Sum of pro-rated amounts equals full monthly price (₹3,800 = 380,000 paise)
        assert bill_amit.amount_paise + bill_priya.amount_paise == 380000
        assert bill_amit.amount_paise == 190000
        assert bill_priya.amount_paise == 190000


def test_transfer_with_prior_pause_retains_pause_on_outgoing_only(transfer_app):
    app, _, _ = transfer_app
    with app.app_context():
        amit = get_customer_by_phone("9876543210")

        # Amit pauses on Friday Sep 4 (1 weekday)
        create_pause(amit.id, date(2026, 9, 4), date(2026, 9, 4), "Dentist visit")

        # Transfer on Sep 16
        priya, _ = transfer_subscription(
            from_customer=amit,
            new_phone="9812345678",
            new_name="Priya Nair",
            transfer_date=date(2026, 9, 16),
        )

        amit_updated = get_customer_by_phone("9876543210")

        bill_amit = compute_bill(
            plan=amit_updated.plan,
            customer=amit_updated,
            pauses=get_pauses_for_customer(amit_updated.id),
            year=2026,
            month=9,
        )
        bill_priya = compute_bill(
            plan=priya.plan,
            customer=priya,
            pauses=get_pauses_for_customer(priya.id),
            year=2026,
            month=9,
        )

        # Amit was paused 1 day -> 10 delivered days
        assert bill_amit.paused_days == 1
        assert bill_amit.delivered_days == 10

        # Priya has 0 pauses -> 11 delivered days
        assert bill_priya.paused_days == 0
        assert bill_priya.delivered_days == 11

        # Pro-rated amounts:
        # Amit: round(380000 * 10 / 22) = 172727 paise (₹1,727.27)
        # Priya: round(380000 * 11 / 22) = 190000 paise (₹1,900.00)
        assert bill_amit.amount_paise == 172727
        assert bill_priya.amount_paise == 190000


def test_transfer_caps_open_ended_pause(transfer_app):
    app, _, _ = transfer_app
    with app.app_context():
        amit = get_customer_by_phone("9876543210")
        # Open-ended pause starting Sep 10
        create_pause(amit.id, date(2026, 9, 10), None, "Traveling")

        # Transfer on Sep 16
        priya, _ = transfer_subscription(
            from_customer=amit,
            new_phone="9812345678",
            new_name="Priya Nair",
            transfer_date=date(2026, 9, 16),
        )

        amit_pauses = get_pauses_for_customer(amit.id)
        assert len(amit_pauses) == 1
        # Pause was capped at Sep 15 (day before transfer)
        assert amit_pauses[0].end_date == date(2026, 9, 15)

        # Priya has no pauses and is active on transfer date
        assert priya.status == Status.ACTIVE
        assert get_pauses_for_customer(priya.id) == []


def test_transfer_validation_errors(transfer_app):
    app, _, _ = transfer_app
    with app.app_context():
        amit = get_customer_by_phone("9876543210")

        # 1. Transfer date on or before customer start date
        with pytest.raises(ValidationError, match="must be strictly after subscription start date"):
            validate_transfer(amit, "9812345678", "New Person", date(2026, 9, 1))

        # 2. Same phone number
        with pytest.raises(ValidationError, match="must be different"):
            validate_transfer(amit, "9876543210", "New Person", date(2026, 9, 15))

        # 3. Invalid phone number
        with pytest.raises(ValidationError, match="10 digits"):
            validate_transfer(amit, "123", "New Person", date(2026, 9, 15))

        # 4. Duplicate phone of an existing other customer
        create_customer("9911223344", "Rohit Sen", "Tower B", amit.plan_id, date(2026, 9, 1))
        with pytest.raises(ValidationError, match="already exists"):
            transfer_subscription(amit, "9911223344", "Duplicate", date(2026, 9, 15))


def test_transfer_web_routes(transfer_app):
    app, client, _ = transfer_app

    # Unauthenticated access redirects to login
    res_unauth = client.get("/customers/9876543210/transfer")
    assert res_unauth.status_code == 302
    assert "/login" in res_unauth.headers["Location"]

    # Log in as owner
    client.post("/login", data={"username": "admin", "password": "tiffin123"})

    # GET transfer page
    res_get = client.get("/customers/9876543210/transfer")
    assert res_get.status_code == 200
    assert b"Transfer Subscription Mid-Cycle" in res_get.data
    assert b"Amit Verma" in res_get.data
    assert b"Carried-Over Plan" in res_get.data

    # POST transfer
    res_post = client.post(
        "/customers/9876543210/transfer",
        data={
            "transfer_date": "2026-09-16",
            "new_name": "Kavita Rao",
            "new_phone": "9822334455",
            "new_address": "Lotus Residency Flat 402",
            "new_email": "kavita@example.com",
            "reason": "Mid-cycle handover",
        },
        follow_redirects=True,
    )
    assert res_post.status_code == 200
    assert b"Subscription successfully transferred to Kavita Rao" in res_post.data
    assert b"Kavita Rao" in res_post.data

    # Check billing sheet shows transfer indicators
    res_billing = client.get("/billing?year=2026&month=9")
    assert res_billing.status_code == 200
    assert b"Transferred to Kavita Rao" in res_billing.data or b"Transferred Out" in res_billing.data
    assert b"Handed over from Amit Verma" in res_billing.data or b"Transferred In" in res_billing.data
