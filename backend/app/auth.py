import base64
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
import hmac
import os
from typing import Callable
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuthSession, User, get_session, utc_now
from .core.config import settings

AUTH_REQUIRED = settings.AUTH_REQUIRED
AUTH_SECRET = settings.AUTH_SECRET


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC). Handle naive datetimes from SQLite."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash password with PBKDF2-SHA256 (120k iterations)."""
    salt_value = salt or uuid4().hex
    digest = pbkdf2_hmac("sha256", password.encode(), salt_value.encode(), 120_000).hex()
    return f"{salt_value}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Verify password against stored hash."""
    if not encoded or "$" not in encoded:
        return False
    salt, expected = encoded.split("$", 1)
    actual = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


def issue_token(user: User, session: Session) -> str:
    """Issue a short-lived, server-revocable bearer session token.
    
    Token format: base64(user_id:org_id:role:session_id:expires_ts:signature)
    Session is stored server-side for revocation support.
    """
    session_id = str(uuid4())
    expires_at = utc_now() + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS)
    payload = f"{user.id}:{user.organization_id}:{user.role}:{session_id}:{int(expires_at.timestamp())}"
    signature = hmac.new(AUTH_SECRET.encode(), payload.encode(), "sha256").hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()
    
    auth_session = AuthSession(
        id=session_id, 
        user_id=user.id, 
        token_hash=sha256(token.encode()).hexdigest(), 
        expires_at=expires_at
    )
    session.add(auth_session)
    session.flush()
    return token


def user_from_token(token: str, session: Session) -> User | None:
    """Extract user from valid, non-revoked token."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, organization_id, role, session_id, expires_at, signature = decoded.split(":", 5)
    except (ValueError, UnicodeDecodeError):
        return None
    
    # Verify signature
    payload = f"{user_id}:{organization_id}:{role}:{session_id}:{expires_at}"
    expected = hmac.new(AUTH_SECRET.encode(), payload.encode(), "sha256").hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    
    # Check expiry
    if int(expires_at) < int(utc_now().timestamp()):
        return None
    
    # Verify server-side session exists and is not revoked
    auth_session = session.get(AuthSession, session_id)
    if not auth_session or auth_session.revoked_at or _ensure_aware(auth_session.expires_at) <= utc_now():
        return None
    
    # Verify token hash matches stored hash
    if not hmac.compare_digest(auth_session.token_hash, sha256(token.encode()).hexdigest()):
        return None
    
    # Load user and verify role consistency
    user = session.scalar(select(User).where(User.id == user_id, User.organization_id == organization_id))
    return user if user and user.role == role else None


def revoke_token(token: str, session: Session) -> None:
    """Revoke a token by marking its server-side session as revoked."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        session_id = decoded.split(":", 6)[3]
    except (ValueError, UnicodeDecodeError):
        return
    
    auth_session = session.get(AuthSession, session_id)
    if auth_session:
        auth_session.revoked_at = utc_now()
        session.flush()


def revoke_user_sessions(user_id: str, session: Session) -> None:
    """Revoke all active sessions for a user (logout all devices)."""
    now = utc_now()
    auth_sessions = session.query(AuthSession).filter(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ).all()
    # Filter in Python to handle timezone-naive datetimes from SQLite
    for auth_session in auth_sessions:
        if _ensure_aware(auth_session.expires_at) > now:
            auth_session.revoked_at = now
    session.flush()


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Extract authenticated user from request."""
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        user = user_from_token(authorization[7:], session)
        if user:
            return user
    
    # Fallback to any admin if auth not required (dev mode only)
    if not AUTH_REQUIRED:
        user = session.scalar(select(User).where(User.role == "ADMIN").limit(1))
        if user:
            return user
    
    raise HTTPException(status_code=401, detail="Authentication required")


def require_roles(*roles: str) -> Callable:
    """Dependency to enforce role-based access control."""
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency
