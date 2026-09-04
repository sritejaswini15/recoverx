"""Simulated Razorpay Provider for RecoverX.
Simulates Razorpay payment and link operations with database persistence and canonical webhook generation.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
import secrets
from uuid import uuid4
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import (
    Customer,
    Invoice,
    Payment,
    PaymentAttempt,
    PaymentLink,
    RecoveryCase,
    Subscription,
)
from app.core.config import settings
from .base import PaymentLinkResult, PaymentProvider, PaymentResult, WebhookPayload


class SimulatedRazorpayProvider:
    """Simulates external Razorpay behavior.
    Manages payment lifecycles and provides webhook payload generation.
    """

    def __init__(self, webhook_secret: str | None = None) -> None:
        self.webhook_secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET", "recoverx_webhook_secret_key_2026")

    def create_payment(self, session: Session, customer_id: str, amount: int, currency: str = "INR") -> PaymentResult:
        customer = session.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")
        payment_id = f"pay_{uuid4().hex[:14]}"
        payment = Payment(
            id=str(uuid4()),
            organization_id=customer.organization_id,
            customer_id=customer.id,
            provider_payment_id=payment_id,
            amount=amount,
            currency=currency,
            status="CREATED",
        )
        session.add(payment)
        session.flush()
        return PaymentResult(payment.provider_payment_id, payment.amount, payment.currency, payment.status)

    def retry_payment(self, session: Session, payment_id: str) -> PaymentResult:
        payment = session.scalar(
            select(Payment).where((Payment.id == payment_id) | (Payment.provider_payment_id == payment_id))
        )
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        attempt_id = f"att_{uuid4().hex[:12]}"
        # If customer reliability > 70%, 80% chance retry succeeds
        customer = session.get(Customer, payment.customer_id)
        reliability = customer.payment_reliability_pct if customer else 70.0
        success = reliability > 70.0

        if success:
            payment.status = "CAPTURED"
            status = "SUCCESS"
            failure_reason = None
        else:
            payment.status = "FAILED"
            status = "FAILED"
            failure_reason = "insufficient_funds"

        attempt = PaymentAttempt(
            id=str(uuid4()),
            payment_id=payment.id,
            provider_attempt_id=attempt_id,
            status=status,
            failure_reason=failure_reason,
        )
        session.add(attempt)
        session.flush()
        return PaymentResult(payment.provider_payment_id, payment.amount, payment.currency, payment.status, failure_reason)

    def create_payment_link(
        self, session: Session, case_id: str, amount: int, description: str = ""
    ) -> PaymentLinkResult:
        existing = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case_id))
        if existing:
            return PaymentLinkResult(
                provider_link_id=existing.provider_link_id or existing.id,
                case_id=existing.case_id,
                amount=existing.amount,
                status=existing.status,
                short_url=existing.short_url,
            )

        provider_link_id = f"plink_{uuid4().hex[:12]}"
        public_token = secrets.token_urlsafe(22)  # Shorter for URL
        # Simulate Razorpay short URL format: https://rzp.io/i/SHORTCODE
        short_url = f"https://rzp.io/i/{public_token}"
        link = PaymentLink(
            id=f"pl_{uuid4().hex[:12]}",
            case_id=case_id,
            provider_link_id=provider_link_id,
            amount=amount,
            status="OPEN",
            short_url=short_url,
            public_token_hash=sha256(public_token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.PAYMENT_LINK_TTL_HOURS),
        )
        session.add(link)
        session.flush()
        return PaymentLinkResult(
            provider_link_id=link.provider_link_id or link.id,
            case_id=link.case_id,
            amount=link.amount,
            status=link.status,
            short_url=link.short_url,
            public_url=f"/pay/{public_token}",
        )

    def fetch_payment(self, session: Session, payment_id: str) -> PaymentResult | None:
        payment = session.scalar(
            select(Payment).where((Payment.id == payment_id) | (Payment.provider_payment_id == payment_id))
        )
        if not payment:
            return None
        return PaymentResult(payment.provider_payment_id, payment.amount, payment.currency, payment.status, payment.failure_reason)

    def fetch_payment_link(self, session: Session, case_id: str) -> PaymentLinkResult | None:
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case_id))
        if not link:
            return None
        return PaymentLinkResult(
            provider_link_id=link.provider_link_id or link.id,
            case_id=link.case_id,
            amount=link.amount,
            status=link.status,
            short_url=link.short_url,
        )

    def cancel_payment_link(self, session: Session, case_id: str) -> bool:
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case_id))
        if not link or link.status in ("PAID", "CANCELLED", "EXPIRED"):
            return False
        link.status = "CANCELLED"
        session.flush()
        return True

    def check_payment_status(self, session: Session, source_id: str) -> str:
        # Check Payment Link
        link = session.scalar(
            select(PaymentLink).where((PaymentLink.id == source_id) | (PaymentLink.provider_link_id == source_id) | (PaymentLink.case_id == source_id))
        )
        if link:
            return link.status
        # Check Payment
        payment = session.scalar(
            select(Payment).where((Payment.id == source_id) | (Payment.provider_payment_id == source_id))
        )
        if payment:
            return payment.status
        return "UNKNOWN"

    def generate_webhook(
        self,
        event_type: str,
        entity_data: dict[str, Any],
        event_id: str | None = None,
    ) -> WebhookPayload:
        """Generates a canonical Razorpay webhook envelope with a valid HMAC SHA-256 signature."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        event_id = event_id or f"evt_{uuid4().hex[:16]}"
        entity_name = "payment"
        if "checkout" in event_type:
            entity_name = "checkout"
        elif "payment_link" in event_type:
            entity_name = "payment_link"
        elif "invoice" in event_type:
            entity_name = "invoice"
        elif "subscription" in event_type:
            entity_name = "subscription"

        body_dict = {
            "id": event_id,
            "entity": "event",
            "account_id": "acc_simulated_razorpay",
            "event": event_type,
            "contains": [entity_name],
            "payload": {
                entity_name: {
                    "entity": entity_data
                }
            },
            "created_at": now_ts,
        }
        raw_body = json.dumps(body_dict, sort_keys=True).encode("utf-8")
        signature = hmac.new(self.webhook_secret.encode("utf-8"), raw_body, sha256).hexdigest()
        return WebhookPayload(
            event=event_type,
            event_id=event_id,
            payload=body_dict,
            signature=signature,
            raw_body=raw_body,
        )
