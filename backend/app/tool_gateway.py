"""Backward-compatible shim for ToolGateway."""
from sqlalchemy.orm import Session
from app.db import RecoveryAction, RecoveryCase
from app.services.tool_gateway import default_gateway


def execute_recovery_tools(
    session: Session,
    provider: any,
    case_id: str,
    action_type: str,
    amount: int,
    channel: str = "WHATSAPP",
) -> RecoveryAction:
    case = session.get(RecoveryCase, case_id)
    if not case:
        raise ValueError(f"Recovery case {case_id} not found")
    return default_gateway.execute_recovery_action(session, case, action_type)
