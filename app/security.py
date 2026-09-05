"""
SahyogSutra Security Module.
Provides Argon2id password hashing, transparent legacy migration,
session token extraction, authoritative user identity checks, and CSRF utilities.
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Optional, Tuple, Dict, Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Request, HTTPException, status
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired

from app.config import SECRET_KEY, SESSION_MAX_AGE, OTP_EXPIRY_SECONDS

logger = logging.getLogger(__name__)

# Argon2id tuned for low RAM (19 MB memory cost as per RFC 9106 recommended minimal)
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # 19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16
)

# --- Password Services ---

def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)

def verify_password(plain_password: str, hashed_or_plain: str) -> Tuple[bool, bool]:
    """
    Verifies a plaintext password against a stored value (Argon2id hash or legacy plaintext).
    Returns (is_valid, needs_rehash).
    """
    if not hashed_or_plain or not plain_password:
        return False, False

    # Check if stored password is an Argon2 hash
    if hashed_or_plain.startswith("$argon2id$") or hashed_or_plain.startswith("$argon2"):
        try:
            _hasher.verify(hashed_or_plain, plain_password)
            needs_rehash = _hasher.check_needs_rehash(hashed_or_plain)
            return True, needs_rehash
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False

    # Safe timing-resistant comparison for legacy plaintext passwords
    if hmac.compare_digest(plain_password, hashed_or_plain):
        # Successfully authenticated against legacy plaintext; signal that it MUST be rehashed
        return True, True

    return False, False

def validate_password(password: str) -> Tuple[bool, str]:
    """Validates password strength/length requirements."""
    if not password:
        return False, "Password cannot be empty"
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if len(password) > 128:
        return False, "Password is too long (maximum 128 characters)"
    return True, ""


# --- Session Cookie Decoding (for SocketIO and external contexts) ---

def decode_session_cookie(cookie_str: str) -> Optional[Dict[str, Any]]:
    """Decodes and validates a Starlette signed session cookie."""
    if not cookie_str:
        return None
    try:
        signer = TimestampSigner(str(SECRET_KEY))
        raw_data = signer.unsign(cookie_str, max_age=SESSION_MAX_AGE)
        data = base64.b64decode(raw_data).decode("utf-8")
        return json.loads(data)
    except (BadSignature, SignatureExpired, Exception):
        return None


# --- Authoritative Identity & Authorization Helpers ---

def get_session_username(request: Request) -> Optional[str]:
    """Extracts username stored in session."""
    username = request.session.get("username")
    if username:
        return str(username).strip().lower()
    return None

async def get_current_user(request: Request, db) -> Optional[Dict[str, Any]]:
    """
    Authoritatively loads current user profile from the database.
    Never trusts role or permissions passed in request session.
    """
    username = get_session_username(request)
    if not username:
        return None

    user = await db.fetchone(
        "SELECT username, name, email, role, events, likes FROM userdetails WHERE username = ?",
        (username,)
    )
    if user:
        return dict(user)
    return None

async def require_authenticated_user(request: Request, db) -> Dict[str, Any]:
    """Requires that a user is actively authenticated; raises HTTP 401 otherwise."""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return user

async def require_admin_user(request: Request, db) -> Dict[str, Any]:
    """Authoritatively verifies that the current user is an admin; raises HTTP 403 otherwise."""
    user = await require_authenticated_user(request, db)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user


# --- CSRF & State-Changing Validation ---

def generate_csrf_token(username_or_ip: str) -> str:
    """Generates a keyed HMAC CSRF token."""
    return hmac.new(
        SECRET_KEY.encode(),
        username_or_ip.encode(),
        hashlib.sha256
    ).hexdigest()

def verify_csrf_token(username_or_ip: str, token: str) -> bool:
    """Verifies a CSRF token."""
    expected = generate_csrf_token(username_or_ip)
    return hmac.compare_digest(expected, token)

