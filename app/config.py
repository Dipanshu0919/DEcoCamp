"""
SahyogSutra Configuration Module.
Centralizes environment variables, secrets, and operational constants.
"""

import os
import secrets
import zoneinfo
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Environment & Server
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production").lower()
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")

# Secret Key for Sessions
# Must be specified in production; fallback to securely generated key in dev
_env_secret = (
    os.environ.get("SECRET_KEY")
    or os.environ.get("FLASK_SECRET")
    or os.environ.get("ECOCAMP_SECRET")
)
if not _env_secret:
    if ENVIRONMENT == "production":
        # Generate an ephemeral random key so it doesn't fail immediately, but warn
        _env_secret = secrets.token_hex(32)
        print("WARNING: No SECRET_KEY set in production! Using ephemeral secret.")
    else:
        _env_secret = "sahyogsutra-dev-secret-key-change-in-prod"

SECRET_KEY = _env_secret

# Database Configuration
SQLITECLOUD_URL = os.environ.get("SQLITECLOUD", "")
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "3"))  # Bounded strictly to 3 for low RAM
DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "20"))

# External Service Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
TGBOTTOKEN = os.environ.get("TGBOTTOKEN", "")

# Timezone
IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Session & Security Settings
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 86400 * 7  # 7 days
SESSION_SAME_SITE = "lax"
SESSION_HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "").lower() in ("true", "1")

# OTP Settings
OTP_EXPIRY_SECONDS = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 5

# Rate Limiter Settings
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 5

