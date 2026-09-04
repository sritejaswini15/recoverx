"""Payment Provider Interface for RecoverX.
Defines operations for payment infrastructure. Real and simulated providers implement this.
"""
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PaymentResult:
    provider_payment_id: str
    amount: int
    currency: str
    status: str
    failure_reason: str | None = None


@dataclass(frozen=True)
class PaymentLinkResult:
    provider_link_id: str
    case_id: str
    amount: int
    status: str
    short_url: str | None = None
    public_url: str | None = None


@dataclass(frozen=True)
class WebhookPayload:
    event: str
    event_id: str
    payload: dict[str, Any]
    signature: str
    raw_body: bytes


@runtime_checkable
class PaymentProvider(Protocol):
    def create_payment(self, session: Session, customer_id: str, amount: int, currency: str = "INR") -> PaymentResult:
        ...

    def retry_payment(self, session: Session, payment_id: str) -> PaymentResult:
        ...

    def create_payment_link(
        self, session: Session, case_id: str, amount: int, description: str = ""
    ) -> PaymentLinkResult:
        ...

    def fetch_payment(self, session: Session, payment_id: str) -> PaymentResult | None:
        ...

    def fetch_payment_link(self, session: Session, case_id: str) -> PaymentLinkResult | None:
        ...

    def cancel_payment_link(self, session: Session, case_id: str) -> bool:
        ...

    def check_payment_status(self, session: Session, source_id: str) -> str:
        ...
