import re
from datetime import date
from typing import Optional

from tiffin.models import Pause


class ValidationError(ValueError):
    """Domain validation error with friendly message."""
    pass


def normalize_phone(raw: str) -> str:
    """
    Normalise raw phone numbers:
    - Strips whitespace, hyphens, parentheses, plus signs.
    - Strips leading +91 or 91 (if 12 digits total).
    - Strips leading 0 (if 11 digits total).
    - Validates exactly 10 digits starting with 6, 7, 8, or 9.
    """
    if not raw:
        raise ValidationError("Phone number is required.")

    # Keep only digits
    digits = re.sub(r"\D", "", raw.strip())

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10:
        raise ValidationError(f"Phone number must have exactly 10 digits (got {len(digits)}: '{raw}').")

    if digits[0] not in ("6", "7", "8", "9"):
        raise ValidationError(f"Invalid phone number '{raw}'. Must start with 6, 7, 8, or 9.")

    return digits


def parse_date(raw: str) -> date:
    """Parse ISO YYYY-MM-DD date string with clear error message."""
    if not raw or not raw.strip():
        raise ValidationError("Date is required.")
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid date format '{raw}'. Please use YYYY-MM-DD.") from e


def validate_pause(
    open_pause: Optional[Pause],
    start_date: date,
    end_date: Optional[date],
) -> None:
    """Validate creating a new pause."""
    if open_pause is not None:
        raise ValidationError(
            f"Customer already has an active open-ended pause starting on {open_pause.start_date}. "
            "Please resume that pause first before adding a new one."
        )

    if end_date is not None and start_date > end_date:
        raise ValidationError(
            f"Pause start date ({start_date}) cannot be after pause end date ({end_date})."
        )


def validate_resume(
    open_pause: Optional[Pause],
    resume_date: date,
) -> None:
    """Validate resuming an open pause."""
    if open_pause is None:
        raise ValidationError("Customer does not have an active open-ended pause to resume.")

    if resume_date < open_pause.start_date:
        raise ValidationError(
            f"Resume date ({resume_date}) cannot be before pause start date ({open_pause.start_date})."
        )


def validate_transfer(
    from_customer,
    new_phone: str,
    new_name: str,
    transfer_date: date,
) -> str:
    """Validate mid-cycle transfer parameters and return normalized new phone."""
    if not new_name or not new_name.strip():
        raise ValidationError("New customer name is required.")

    norm_phone = normalize_phone(new_phone)

    if from_customer is None:
        raise ValidationError("Source customer not found.")

    if norm_phone == from_customer.phone:
        raise ValidationError("New customer phone must be different from current customer phone.")

    if transfer_date <= from_customer.start_date:
        raise ValidationError(
            f"Transfer date ({transfer_date}) must be strictly after subscription start date ({from_customer.start_date})."
        )

    if from_customer.end_date is not None and transfer_date > from_customer.end_date:
        raise ValidationError(
            f"Transfer date ({transfer_date}) cannot be after subscription end date ({from_customer.end_date})."
        )

    return norm_phone

