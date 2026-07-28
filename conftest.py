"""Shared pytest configuration — auto-loaded before every test run.

Sets required env vars before config.py instantiation so tests don't need
inline os.environ.setdefault blocks.
"""
import os

# Set test env vars BEFORE any project imports — config.py instantiates
# Settings at module level, so these must be in place first.
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", '["http://localhost"]')
