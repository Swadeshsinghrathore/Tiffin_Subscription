from datetime import date
import pytest

from tiffin.models import Pause
from tiffin.validators import (
    ValidationError,
    normalize_phone,
    parse_date,
    validate_pause,
    validate_resume,
)


def test_phone_normalization_valid_formats():
    """Verify various common Indian phone formats normalize to clean 10-digits."""
    assert normalize_phone("9876543210") == "9876543210"
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("+91-98765-43210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_phone("919876543210") == "9876543210"
    assert normalize_phone("  8123456789  ") == "8123456789"
    assert normalize_phone("7012345678") == "7012345678"
    assert normalize_phone("6901234567") == "6901234567"


def test_phone_normalization_invalid_cases():
    """Verify invalid phone numbers raise ValidationError."""
    with pytest.raises(ValidationError, match="required"):
        normalize_phone("")

    with pytest.raises(ValidationError, match="10 digits"):
        normalize_phone("12345")

    with pytest.raises(ValidationError, match="10 digits"):
        normalize_phone("98765432101234")

    # Invalid starting digit (must be 6, 7, 8, 9)
    with pytest.raises(ValidationError, match="Must start with 6, 7, 8, or 9"):
        normalize_phone("5123456789")

    with pytest.raises(ValidationError, match="Must start with 6, 7, 8, or 9"):
        normalize_phone("1234567890")


def test_parse_date():
    """Verify ISO date parsing."""
    assert parse_date("2024-03-01") == date(2024, 3, 1)

    with pytest.raises(ValidationError, match="Date is required"):
        parse_date("")

    with pytest.raises(ValidationError, match="Invalid date format"):
        parse_date("01-03-2024")

    with pytest.raises(ValidationError, match="Invalid date format"):
        parse_date("invalid-date")


def test_validate_pause_rules():
    """Verify pause validation rules."""
    # Cannot add pause when an open-ended pause exists
    open_p = Pause(
        id=1,
        customer_id=1,
        start_date=date(2024, 3, 10),
        end_date=None,
    )
    with pytest.raises(ValidationError, match="active open-ended pause"):
        validate_pause(open_p, date(2024, 3, 15), None)

    # Start date cannot be after end date
    with pytest.raises(ValidationError, match="cannot be after pause end date"):
        validate_pause(None, date(2024, 3, 15), date(2024, 3, 10))

    # Valid pause passes
    validate_pause(None, date(2024, 3, 10), date(2024, 3, 15))
    validate_pause(None, date(2024, 3, 10), None)


def test_validate_resume_rules():
    """Verify resume validation rules."""
    # Cannot resume without an open pause
    with pytest.raises(ValidationError, match="does not have an active open-ended pause"):
        validate_resume(None, date(2024, 3, 15))

    open_p = Pause(
        id=1,
        customer_id=1,
        start_date=date(2024, 3, 10),
        end_date=None,
    )

    # Cannot resume before start date
    with pytest.raises(ValidationError, match="cannot be before pause start date"):
        validate_resume(open_p, date(2024, 3, 5))

    # Valid resume date passes
    validate_resume(open_p, date(2024, 3, 10))
    validate_resume(open_p, date(2024, 3, 15))
