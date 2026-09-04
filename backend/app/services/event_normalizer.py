"""Event Normalizer Service.
Converts heterogeneous external Razorpay/provider events into the canonical RecoverX RevenueEvent.
"""
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class CanonicalRevenueEvent(BaseModel):
    event_type: str
    customer_id: str
    amount: int
    currency: str = "INR"
    source: str = "razorpay"
    source_entity: str = "payment"
    source_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


EVENT_TYPE_MAPPING = {
    "payment.failed": "PAYMENT_FAILURE",
    "payment.authorized": "PAYMENT_CAPTURED",
    "payment.captured": "PAYMENT_CAPTURED",
    "payment_link.paid": "PAYMENT_LINK_PAID",
    "payment_link.partially_paid": "PAYMENT_LINK_PAID",
    "payment_link.expired": "PAYMENT_LINK_EXPIRED",
    "payment_link.cancelled": "PAYMENT_LINK_CANCELLED",
    "payment_link.abandoned": "PAYMENT_LINK_ABANDONED",
    "invoice.paid": "INVOICE_PAID",
    "invoice.partially_paid": "INVOICE_OVERDUE",
    "invoice.expired": "INVOICE_OVERDUE",
    "invoice.overdue": "INVOICE_OVERDUE",
    "subscription.charged": "SUBSCRIPTION_CHARGED",
    "subscription.halted": "SUBSCRIPTION_HALTED",
    "subscription.cancelled": "SUBSCRIPTION_CANCELLED",
    "subscription.pending": "SUBSCRIPTION_PENDING",
    "checkout.abandoned": "CHECKOUT_ABANDONED",
}


def normalize_event(raw_body: dict[str, Any]) -> CanonicalRevenueEvent:
    """Normalizes an incoming webhook payload or simulation body into a CanonicalRevenueEvent."""
    # 1. If payload already in canonical format (e.g. from internal simulator)
    if "event_type" in raw_body and ("payment" not in raw_body or "contains" not in raw_body):
        event_type = raw_body.get("event_type", "PAYMENT_FAILURE")
        # Map canonical alias if passed with dot notation
        event_type = EVENT_TYPE_MAPPING.get(event_type, event_type)
        return CanonicalRevenueEvent(
            event_type=event_type,
            customer_id=raw_body.get("customer_id", "cus_default"),
            amount=int(raw_body.get("amount", 0)),
            currency=raw_body.get("currency", "INR"),
            source=raw_body.get("source", "simulated_razorpay"),
            source_entity=raw_body.get("source_entity", "payment"),
            source_id=raw_body.get("id") or raw_body.get("source_id", "src_unknown"),
            timestamp=raw_body.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            metadata=raw_body.get("metadata", {}),
        )

    # 2. Standard Razorpay webhook envelope structure:
    # {"entity": "event", "event": "payment.failed", "payload": {"payment": {"entity": {...}}}}
    raw_event = raw_body.get("event")
    if raw_event not in EVENT_TYPE_MAPPING:
        raise ValueError(f"Unsupported Razorpay event: {raw_event or 'missing'}")
    event_type = EVENT_TYPE_MAPPING[raw_event]
    
    payload = raw_body.get("payload", {})
    entity_data = {}
    source_entity = "payment"

    for candidate_key in ("payment", "payment_link", "invoice", "subscription", "checkout"):
        if candidate_key in payload:
            entity_data = payload[candidate_key].get("entity", {})
            source_entity = candidate_key
            break

    amount = int(entity_data.get("amount", raw_body.get("amount", 0)))
    if amount <= 0:
        raise ValueError("Webhook amount must be greater than zero")
    # Razorpay amounts in paise are divided by 100 if > 100000 and has sub-units, or if currency is INR and amount has 2 extra decimal digits
    # In RecoverX synthetic environment, amounts are integer rupees or paise:
    if amount > 100000 and "notes" in entity_data:
        amount = amount // 100

    customer_id = (
        entity_data.get("customer_id")
        or entity_data.get("notes", {}).get("customer_id")
        or raw_body.get("customer_id", "cus_default")
    )
    source_id = entity_data.get("id") or raw_body.get("id", f"src_{raw_event}")

    metadata = {
        "raw_event": raw_event,
        "method": entity_data.get("method"),
        "error_code": entity_data.get("error_code"),
        "error_description": entity_data.get("error_description"),
        "notes": entity_data.get("notes", {}),
    }

    return CanonicalRevenueEvent(
        event_type=event_type,
        customer_id=customer_id,
        amount=amount,
        currency=entity_data.get("currency", "INR"),
        source="razorpay",
        source_entity=source_entity,
        source_id=source_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=metadata,
    )
