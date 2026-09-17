from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


class Status(str, Enum):
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"

    @property
    def label(self) -> str:
        return {
            Status.NOT_STARTED: "Not Started",
            Status.ACTIVE: "Active",
            Status.PAUSED: "Paused",
            Status.ENDED: "Ended",
        }[self]

    @property
    def badge_class(self) -> str:
        return {
            Status.NOT_STARTED: "badge-not-started",
            Status.ACTIVE: "badge-active",
            Status.PAUSED: "badge-paused",
            Status.ENDED: "badge-ended",
        }[self]


@dataclass
class Plan:
    id: Optional[int]
    code: str
    name: str
    monthly_price_paise: int
    is_active: bool = True

    @property
    def monthly_price_rupees(self) -> float:
        return self.monthly_price_paise / 100.0

    @property
    def monthly_price_formatted(self) -> str:
        return f"₹{self.monthly_price_paise / 100:,.2f}"


@dataclass
class SubscriptionTransfer:
    id: Optional[int]
    from_customer_id: int
    to_customer_id: int
    transfer_date: date
    plan_id: int
    reason: Optional[str] = None
    created_at: Optional[str] = None
    from_customer_name: Optional[str] = None
    from_customer_phone: Optional[str] = None
    to_customer_name: Optional[str] = None
    to_customer_phone: Optional[str] = None
    plan_name: Optional[str] = None


@dataclass
class Customer:
    id: Optional[int]
    phone: str
    name: str
    address: Optional[str]
    plan_id: int
    start_date: date
    end_date: Optional[date] = None
    created_at: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[Plan] = None
    status: Optional[Status] = None
    active_pause: Optional["Pause"] = None
    transferred_to: Optional[SubscriptionTransfer] = None
    transferred_from: Optional[SubscriptionTransfer] = None


@dataclass
class NotificationLog:
    id: Optional[int]
    customer_id: int
    recipient_email: str
    subject: str
    delivery_date: date
    status: str
    details: Optional[str] = None
    sent_at: Optional[str] = None
    customer_name: Optional[str] = None


@dataclass
class Pause:
    id: Optional[int]
    customer_id: int
    start_date: date
    end_date: Optional[date] = None
    reason: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.end_date is None


@dataclass
class Holiday:
    day: date
    label: str


@dataclass
class BillLine:
    customer: Customer
    plan: Plan
    year: int
    month: int
    plan_price_paise: int
    billable_days: int
    delivered_days: int
    paused_days: int
    amount_paise: int
    is_frozen: bool = False
    generated_at: Optional[str] = None
    transfer_info: Optional[SubscriptionTransfer] = None

    @property
    def amount_formatted(self) -> str:
        return f"₹{self.amount_paise / 100:,.2f}"

    @property
    def plan_price_formatted(self) -> str:
        return f"₹{self.plan_price_paise / 100:,.2f}"

    @property
    def daily_rate_formatted(self) -> str:
        if self.billable_days > 0:
            rate = (self.plan_price_paise / 100.0) / self.billable_days
            return f"₹{rate:,.2f}"
        return "₹0.00"


@dataclass
class Owner:
    id: Optional[int]
    username: str
    email: str
    password_hash: str
    business_name: str
    created_at: Optional[str] = None

