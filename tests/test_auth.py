import os
import tempfile
import pytest

from app import create_app
from tiffin.db import init_db


@pytest.fixture
def auth_client():
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
        yield client

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_landing_page_renders(auth_client):
    res = auth_client.get("/")
    assert res.status_code == 200
    assert b"Exact Pro-Rata Invoicing" in res.data
    assert b"Live Interactive Simulator" in res.data
    assert b"sim-plan" in res.data


def test_demo_login_success(auth_client):
    res_login = auth_client.post(
        "/login",
        data={
            "username": "admin",
            "password": "tiffin123",
        },
        follow_redirects=True,
    )
    assert res_login.status_code == 200
    assert b"Welcome back, Annapurna Tiffin Kitchen" in res_login.data
    assert b"Sign Out" in res_login.data


def test_login_invalid_password(auth_client):
    res_fail = auth_client.post(
        "/login",
        data={
            "username": "admin",
            "password": "wrongpassword",
        },
        follow_redirects=True,
    )
    assert res_fail.status_code == 200
    assert b"Invalid username or password" in res_fail.data


def test_owner_signup_and_logout(auth_client):
    # Signup new owner
    res_signup = auth_client.post(
        "/signup",
        data={
            "business_name": "Royal Gujarati Tiffin",
            "username": "royal_kitchen",
            "email": "royal@gujaratitiffin.com",
            "password": "secretpassword",
            "confirm_password": "secretpassword",
        },
        follow_redirects=True,
    )
    assert res_signup.status_code == 200
    assert b"Royal Gujarati Tiffin" in res_signup.data

    # Logout
    res_logout = auth_client.get("/logout", follow_redirects=True)
    assert res_logout.status_code == 200
    assert b"signed out successfully" in res_logout.data
    assert b"Owner Login" in res_logout.data


def test_protected_route_requires_login(auth_client):
    # Unauthenticated post to new customer redirects to login
    res = auth_client.post(
        "/customers/new",
        data={
            "phone": "9876543210",
            "name": "Test Person",
            "plan_id": "1",
            "start_date": "2024-03-01",
        },
    )
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]
