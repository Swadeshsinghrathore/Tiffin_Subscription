import os
import tempfile
from datetime import date
import pytest

from tiffin.db import get_db, init_db
from tiffin.models import Status
from tiffin.repository import (
    create_customer,
    create_pause,
    end_subscription,
    freeze_bills,
    get_all_plans,
    get_customer_by_phone,
    get_customers,
    get_frozen_bills_for_month,
    get_open_pause_for_customer,
    get_pauses_for_customer,
    has_frozen_bills,
    resume_pause,
    unfreeze_bills,
)
from tiffin.validators import ValidationError


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    # Monkeypatch repository get_db
    import tiffin.repository as repo
    old_get_db = repo.get_db
    repo.get_db = lambda: get_db(path)
    yield path
    repo.get_db = old_get_db
    try:
        os.remove(path)
    except OSError:
        pass


def test_seed_plans(temp_db):
    plans = get_all_plans()
    assert len(plans) == 3
    codes = {p.code for p in plans}
    assert "STD_VEG" in codes
    assert "DLX_VEG" in codes
    assert "MINI_MEAL" in codes


def test_customer_crud_and_normalization(temp_db):
    # Subscribe with formatted phone
    cust = create_customer(
        phone="+91-98765-43210",
        name="Asha Patel",
        address="Flat 4B, Sunrise Apts",
        plan_id=1,
        start_date=date(2024, 3, 1),
    )
    assert cust.phone == "9876543210"
    assert cust.name == "Asha Patel"
    assert cust.status == Status.ACTIVE

    # Lookup by phone with spaces
    found = get_customer_by_phone("98765 43210")
    assert found is not None
    assert found.id == cust.id

    # Duplicate phone error
    with pytest.raises(ValidationError, match="already exists"):
        create_customer(
            phone="09876543210",
            name="Another Person",
            address="",
            plan_id=1,
            start_date=date(2024, 3, 1),
        )


def test_pause_and_resume_flow(temp_db):
    cust = create_customer(
        phone="9876543210",
        name="Asha Patel",
        address="",
        plan_id=1,
        start_date=date(2024, 3, 1),
    )

    # Initially Active
    assert cust.status == Status.ACTIVE

    # Create open-ended pause
    p = create_pause(cust.id, date(2024, 3, 10), None, "Vacation")
    assert p.is_open is True

    open_p = get_open_pause_for_customer(cust.id)
    assert open_p is not None
    assert open_p.id == p.id

    # Resume the pause
    resume_pause(p.id, date(2024, 3, 15))
    open_p_after = get_open_pause_for_customer(cust.id)
    assert open_p_after is None

    pauses = get_pauses_for_customer(cust.id)
    assert len(pauses) == 1
    assert pauses[0].end_date == date(2024, 3, 15)
