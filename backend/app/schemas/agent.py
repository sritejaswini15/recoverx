"""Pydantic schemas for AI Agent decisioning and structured output.
"""
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class RecoveryAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    MONITOR = "MONITOR"
    PAYMENT_LINK = "PAYMENT_LINK"
    PAYMENT_RETRY = "PAYMENT_RETRY"
    REMINDER = "REMINDER"
    PERSONALIZED_OUTREACH = "PERSONALIZED_OUTREACH"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    FOLLOW_UP = "FOLLOW_UP"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    STOP = "STOP"


class RecoveryDecision(BaseModel):
    diagnosis: str = Field(..., description="Comprehensive diagnosis of what happened and why")
    root_cause: str = Field(..., description="Categorized root cause for the revenue loss")
    recovery_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated likelihood of successful recovery")
    recommended_action: RecoveryAction = Field(..., description="Action chosen from controlled vocabulary")
    reasoning: str = Field(..., description="Structured explanation of why this action was selected")
    confidence: float = Field(..., ge=0.0, le=1.0, description="AI confidence in this recommendation")
    communication_tone: str = Field(default="empathetic", description="Tone for communication")
    suggested_language: str = Field(default="English", description="Suggested communication language")
