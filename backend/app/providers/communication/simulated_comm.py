"""Simulated WhatsApp and Email Communication Providers.
Persists communication records with realistic lifecycle statuses and multi-language support.
"""
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Communication, Customer
from .base import MessageResult


class SimulatedWhatsAppProvider:
    channel = "WHATSAPP"

    def send_message(
        self,
        session: Session,
        case_id: str,
        customer_id: str,
        recipient: str,
        content: str,
    ) -> MessageResult:
        provider_message_id = f"wamid_{uuid4().hex[:14]}"
        comm = Communication(
            id=str(uuid4()),
            case_id=case_id,
            customer_id=customer_id,
            channel=self.channel,
            direction="OUTBOUND",
            content=content,
            provider="simulated_whatsapp",
            provider_message_id=provider_message_id,
            status="SENT",
        )
        session.add(comm)
        session.flush()
        return MessageResult(
            message_id=comm.id,
            channel=self.channel,
            recipient=recipient,
            status=comm.status,
            content=comm.content,
        )

    def check_delivery_status(self, session: Session, message_id: str) -> str:
        comm = session.get(Communication, message_id)
        if not comm:
            return "NOT_FOUND"
        # Transition SENT -> DELIVERED -> OPENED
        if comm.status == "SENT":
            comm.status = "DELIVERED"
        elif comm.status == "DELIVERED":
            comm.status = "OPENED"
        session.flush()
        return comm.status


class SimulatedEmailProvider:
    channel = "EMAIL"

    def send_message(
        self,
        session: Session,
        case_id: str,
        customer_id: str,
        recipient: str,
        content: str,
    ) -> MessageResult:
        provider_message_id = f"msg_{uuid4().hex[:14]}"
        comm = Communication(
            id=str(uuid4()),
            case_id=case_id,
            customer_id=customer_id,
            channel=self.channel,
            direction="OUTBOUND",
            content=content,
            provider="simulated_email",
            provider_message_id=provider_message_id,
            status="SENT",
        )
        session.add(comm)
        session.flush()
        return MessageResult(
            message_id=comm.id,
            channel=self.channel,
            recipient=recipient,
            status=comm.status,
            content=comm.content,
        )

    def check_delivery_status(self, session: Session, message_id: str) -> str:
        comm = session.get(Communication, message_id)
        if not comm:
            return "NOT_FOUND"
        if comm.status == "SENT":
            comm.status = "DELIVERED"
        elif comm.status == "DELIVERED":
            comm.status = "OPENED"
        session.flush()
        return comm.status
