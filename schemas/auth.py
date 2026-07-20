"""Pydantic request/response models for the seller authentication endpoints (section 2.8).

These schemas never carry secret material (OTP codes at rest, token hashes, refresh
tokens) in responses — see PLAN.md 2.8 security rules.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OTPRequestBody(BaseModel):
    """Body for POST /auth/otp/request."""

    phone_number: str = Field(..., examples=["09123456789"])


class OTPVerifyBody(BaseModel):
    """Body for POST /auth/otp/verify."""

    phone_number: str = Field(..., examples=["09123456789"])
    code: str = Field(..., examples=["123456"])


class MessageResponse(BaseModel):
    """Generic single-message response (e.g. OTP request acknowledgement)."""

    message: str


class TokenResponse(BaseModel):
    """Access-token response returned by OTP verify, OAuth callback, and refresh."""

    access_token: str
    expires_in: int


class MeResponse(BaseModel):
    """Response for GET /auth/me — the authenticated seller's own profile.

    Never includes tokens, token hashes, or any secret material.
    """

    id: int
    phone_number: str | None = None
    divar_user_id: str | None = None
    created_at: datetime
