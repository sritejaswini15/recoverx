"""Razorpay HTTP adapter.

Financial actions remain behind the RecoverX Tool Gateway. This adapter is only
selected when PAYMENT_PROVIDER=razorpay and credentials are configured.
"""
import base64
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Payment, PaymentLink
from .base import PaymentLinkResult, PaymentProvider, PaymentResult


class RazorpayProvider:
    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self.key_id = key_id or settings.RAZORPAY_KEY_ID
        self.key_secret = key_secret or settings.RAZORPAY_KEY_SECRET
        self.base_url = "https://api.razorpay.com/v1"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.key_id or not self.key_secret:
            raise RuntimeError("Razorpay credentials are not configured")
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Razorpay request failed: {exc}") from exc

    def create_payment(self, session: Session, customer_id: str, amount: int, currency: str = "INR") -> PaymentResult:
        raise RuntimeError(
            "Razorpay does not expose a server-side payment-creation API; use create_payment_link "
            "or the merchant Checkout flow"
        )

    def retry_payment(self, session: Session, payment_id: str) -> PaymentResult:
        payment = session.scalar(
            select(Payment).where(
                (Payment.id == payment_id) | (Payment.provider_payment_id == payment_id)
            )
        )
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")
        if payment.status == "CAPTURED":
            return PaymentResult(payment.provider_payment_id, payment.amount, payment.currency, payment.status)

        # Razorpay's server API has no generic retry operation. Capture is only
        # valid for an authorized payment; the provider status is re-read first
        # so RecoverX never turns a failed payment into a blind duplicate charge.
        current = self.fetch_payment(session, payment.provider_payment_id)
        if not current or current.status not in ("AUTHORIZED", "CREATED"):
            raise RuntimeError(
                f"Razorpay payment {payment.provider_payment_id} cannot be retried from status "
                f"{current.status if current else 'UNKNOWN'}; create a new Checkout or Payment Link"
            )
        response = self._request(
            "POST",
            f"/payments/{payment.provider_payment_id}/capture",
            {"amount": payment.amount * 100, "currency": payment.currency},
        )
        payment.status = str(response.get("status", "captured")).upper()
        session.flush()
        return PaymentResult(
            provider_payment_id=response.get("id", payment.provider_payment_id),
            amount=int(response.get("amount", payment.amount * 100)) // 100,
            currency=response.get("currency", payment.currency),
            status=payment.status,
        )

    def create_payment_link(self, _session: Session, case_id: str, amount: int, _description: str = "") -> PaymentLinkResult:
        response = self._request(
            "POST",
            "/payment_links",
            {
                "amount": amount * 100,
                "currency": "INR",
                "accept_partial": False,
                "description": _description or f"RecoverX recovery case {case_id}",
                "reference_id": case_id,
                "notes": {"recoverx_case_id": case_id},
            },
        )
        return PaymentLinkResult(
            provider_link_id=response["id"],
            case_id=case_id,
            amount=amount,
            status=response.get("status", "created").upper(),
            short_url=response.get("short_url"),
        )

    def fetch_payment(self, _session: Session, payment_id: str) -> PaymentResult | None:
        try:
            response = self._request("GET", f"/payments/{payment_id}")
        except RuntimeError:
            return None
        return PaymentResult(
            provider_payment_id=response["id"],
            amount=int(response.get("amount", 0)) // 100,
            currency=response.get("currency", "INR"),
            status=response.get("status", "unknown").upper(),
        )

    def fetch_payment_link(self, session: Session, case_id: str) -> PaymentLinkResult | None:
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case_id))
        if not link or not link.provider_link_id:
            return None
        response = self._request("GET", f"/payment_links/{link.provider_link_id}")
        link.status = str(response.get("status", link.status)).upper()
        link.short_url = response.get("short_url", link.short_url)
        session.flush()
        return PaymentLinkResult(
            provider_link_id=response.get("id", link.provider_link_id),
            case_id=case_id,
            amount=int(response.get("amount", link.amount * 100)) // 100,
            status=link.status,
            short_url=link.short_url,
        )

    def cancel_payment_link(self, session: Session, case_id: str) -> bool:
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case_id))
        if not link or not link.provider_link_id or link.status in ("PAID", "CANCELLED", "EXPIRED"):
            return False
        response = self._request("POST", f"/payment_links/{link.provider_link_id}/cancel")
        link.status = str(response.get("status", "cancelled")).upper()
        session.flush()
        return link.status == "CANCELLED"

    def check_payment_status(self, session: Session, source_id: str) -> str:
        payment = self.fetch_payment(session, source_id)
        return payment.status if payment else "UNKNOWN"
