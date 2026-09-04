"""Communication Provider interface for multi-channel recovery messaging.
"""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class MessageResult:
    message_id: str
    channel: str
    recipient: str
    status: str
    content: str


@runtime_checkable
class CommunicationProvider(Protocol):
    def send_message(
        self,
        session: Session,
        case_id: str,
        customer_id: str,
        channel: str,
        recipient: str,
        content: str,
    ) -> MessageResult:
        ...

    def check_delivery_status(self, session: Session, message_id: str) -> str:
        ...
