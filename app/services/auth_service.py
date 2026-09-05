"""
SahyogSutra Authentication & OTP Service.
Handles Argon2id password verification, transparent migration of legacy plaintext passwords,
secure database-backed OTP lifecycle, and user registration.
"""

import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional, Tuple, Dict, Any

from app.config import SECRET_KEY, OTP_EXPIRY_SECONDS, OTP_MAX_ATTEMPTS
from app.security import hash_password, verify_password, validate_password
from app.services.email_service import send_mail_async, sendlog, get_otp_email_html

logger = logging.getLogger(__name__)


def _hash_otp(plain_otp: str) -> str:
    """Computes a keyed HMAC SHA-256 hash of the plain OTP."""
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        plain_otp.strip().encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


async def create_and_send_otp(
    email: str,
    purpose: str,
    db,
    subject: str = "Verification OTP - SahyogSutra"
) -> Tuple[bool, str]:
    """
    Generates a secure 6-digit OTP, stores its hash in otp_verifications,
    and dispatches the email. Invalidates previous active OTPs for the same identifier & purpose.
    """
    email_clean = email.strip().lower()
    now = int(time.time())

    # Invalidate any existing unused OTPs for this email and purpose
    await db.execute(
        "UPDATE otp_verifications SET used_at = ? WHERE identifier = ? AND purpose = ? AND used_at IS NULL",
        (now, email_clean, purpose)
    )

    # Cryptographically secure 6-digit OTP
    otp_int = secrets.randbelow(900000) + 100000
    otp_str = str(otp_int)
    otp_hashed = _hash_otp(otp_str)
    expires_at = now + OTP_EXPIRY_SECONDS

    # Insert into database
    await db.execute(
        """
        INSERT INTO otp_verifications (identifier, purpose, otp_hash, expires_at, attempts, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (email_clean, purpose, otp_hashed, expires_at, now)
    )
    await db.commit()

    # Dispatch email asynchronously
    email_content = get_otp_email_html(otp_str)
    await send_mail_async(email_clean, subject, email_content, mail_type="html")

    logger.info("Dispatched OTP for purpose '%s' to %s", purpose, email_clean)
    return True, f"OTP sent to {email_clean}! Please check your spam folder if you cannot find it."


async def verify_stored_otp(
    email: str,
    purpose: str,
    entered_otp: str,
    db
) -> Tuple[bool, str]:
    """
    Verifies an entered OTP against the active hash in otp_verifications.
    Enforces maximum attempts and expiration. Marks OTP as used upon success or failure limit.
    """
    email_clean = email.strip().lower()
    otp_input = str(entered_otp or "").strip()
    if not otp_input:
        return False, "OTP cannot be empty"

    now = int(time.time())

    # Fetch latest active OTP record
    row = await db.fetchone(
        """
        SELECT id, otp_hash, expires_at, attempts
        FROM otp_verifications
        WHERE identifier = ? AND purpose = ? AND used_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (email_clean, purpose)
    )

    if not row:
        return False, "No active OTP found. Please request a new OTP."

    otp_id = row["id"]
    otp_hash = row["otp_hash"]
    expires_at = row["expires_at"]
    attempts = row["attempts"]

    # Check expiration
    if now > expires_at:
        await db.execute("UPDATE otp_verifications SET used_at = ? WHERE id = ?", (now, otp_id))
        await db.commit()
        return False, "OTP has expired. Please request a new one."

    # Check maximum attempts limit
    if attempts >= OTP_MAX_ATTEMPTS:
        await db.execute("UPDATE otp_verifications SET used_at = ? WHERE id = ?", (now, otp_id))
        await db.commit()
        return False, "Maximum verification attempts exceeded. Please request a new OTP."

    # Increment attempts
    await db.execute(
        "UPDATE otp_verifications SET attempts = attempts + 1 WHERE id = ?",
        (otp_id,)
    )
    await db.commit()

    # Timing-safe comparison of OTP hashes
    expected_hash = _hash_otp(otp_input)
    if not hmac.compare_digest(expected_hash, otp_hash):
        return False, "Wrong OTP!"

    # Mark as successfully used
    await db.execute("UPDATE otp_verifications SET used_at = ? WHERE id = ?", (now, otp_id))
    await db.commit()
    return True, "OTP verified successfully."


async def authenticate_user_credentials(
    username_or_email: str,
    password: str,
    db
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Authenticates user login with transparent Argon2id password upgrade.
    """
    identifier = username_or_email.strip().lower()

    row = await db.fetchone(
        "SELECT username, password, name, email, role, events, likes FROM userdetails WHERE username = ? OR email = ?",
        (identifier, identifier)
    )
    if not row:
        return False, "No user found with that username or email.", None

    stored_password = row["password"] or ""
    is_valid, needs_rehash = verify_password(password, stored_password)

    if not is_valid:
        return False, "Wrong Password", None

    # Transparent migration: rehash legacy plaintext or outdated Argon2 parameter hashes
    if needs_rehash:
        try:
            new_hash = hash_password(password)
            await db.execute(
                "UPDATE userdetails SET password = ? WHERE username = ?",
                (new_hash, row["username"])
            )
            await db.commit()
            logger.info("Migrated password for user '%s' to Argon2id.", row["username"])
        except Exception as e:
            logger.error("Failed to rehash password for user %s: %s", row["username"], e)

    user_info = {
        "username": row["username"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"] or "user",
    }
    return True, "Login Success", user_info


async def register_new_user(
    username: str,
    password: str,
    cpassword: str,
    name: str,
    email: str,
    otp: str,
    db
) -> Tuple[bool, str]:
    """Validates inputs, verifies OTP, and registers a new user with Argon2id hash."""
    uname = username.strip().lower()
    user_email = email.strip().lower()
    user_name = name.strip()

    if not uname or len(uname) < 3 or len(uname) > 20:
        return False, "Username must be between 3 and 20 characters."

    valid_pass, pass_err = validate_password(password)
    if not valid_pass:
        return False, pass_err

    if password != cpassword:
        return False, "Wrong Confirm Password"

    # Check for existing user
    user_exists = await db.fetchone(
        "SELECT username FROM userdetails WHERE username = ?",
        (uname,)
    )
    if user_exists:
        return False, "Username Already Exists"

    email_exists = await db.fetchone(
        "SELECT email FROM userdetails WHERE email = ?",
        (user_email,)
    )
    if email_exists:
        return False, "Email Already Exists"

    # Verify OTP
    otp_ok, otp_msg = await verify_stored_otp(user_email, "signup", otp, db)
    if not otp_ok:
        return False, otp_msg

    # Securely hash password with Argon2id
    password_hashed = hash_password(password)

    await db.execute(
        "INSERT INTO userdetails (username, password, name, email, role) VALUES (?, ?, ?, ?, 'user')",
        (uname, password_hashed, user_name, user_email)
    )
    await db.commit()

    sendlog(f"New Signup: {user_name} ({uname})")
    return True, "Signup Success"


async def reset_user_password(
    identifier: str,
    new_password: str,
    confirm_password: str,
    otp: str,
    db
) -> Tuple[bool, str]:
    """Verifies OTP and resets user password with Argon2id hash."""
    ident = identifier.strip().lower()
    user = await db.fetchone(
        "SELECT username, email FROM userdetails WHERE username = ? OR email = ?",
        (ident, ident)
    )
    if not user:
        return False, "Email/Username does not exist."

    user_email = user["email"]

    valid_pass, pass_err = validate_password(new_password)
    if not valid_pass:
        return False, pass_err

    if new_password != confirm_password:
        return False, "Wrong Confirm Password!"

    # Verify OTP
    otp_ok, otp_msg = await verify_stored_otp(user_email, "reset", otp, db)
    if not otp_ok:
        return False, otp_msg

    # Hash with Argon2id
    hashed = hash_password(new_password)
    await db.execute(
        "UPDATE userdetails SET password = ? WHERE email = ?",
        (hashed, user_email)
    )
    await db.commit()

    sendlog(f"Password reset completed for user {user['username']}")
    return True, "Password Change Success!"

