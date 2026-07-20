"""SMS delivery service — abstract interface + a dev-only console implementation.

No concrete production SMS provider (Kavenegar, sms.ir, etc.) is chosen or integrated
yet. Authentication endpoints (section 2.8) depend ONLY on the `SMSService` protocol,
never on a specific provider's SDK — so adding a real provider later means writing one
new class implementing `SMSService`, with no changes to the auth flow.

Failure contract (per PLAN.md 2.8): `send_otp` raises on delivery failure. The dev
`ConsoleSMSService` never raises. A future real provider raises on timeout / network
error / non-success response, and the OTP-request endpoint catches it and returns 503.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger("sms")


@runtime_checkable
class SMSService(Protocol):
    """Abstract SMS delivery interface. Auth endpoints depend on this, not on a provider."""

    async def send_otp(self, phone_number: str, code: str) -> None:
        """Deliver the plaintext OTP `code` to `phone_number`.

        Must raise on delivery failure so the caller can invalidate the OTP and
        surface an error. Returns None on success.
        """
        ...


class ConsoleSMSService:
    """Development/testing implementation ONLY — logs the OTP instead of sending SMS.

    Not production code: it performs no real delivery and never raises. Clearly named
    so it is obviously unsuitable for production use.
    """

    async def send_otp(self, phone_number: str, code: str) -> None:
        # NOTE: logging the plaintext OTP is acceptable for this local-dev stub only.
        # A real provider implementation must never log the code.
        logger.info(
            "ConsoleSMSService: OTP for %s is %s (dev stub — no SMS actually sent)",
            phone_number,
            code,
        )


# Single shared dev instance. Injected into endpoints via FastAPI `Depends(get_sms_service)`
# so tests can override it with a capturing mock through `app.dependency_overrides`.
_sms_service: SMSService = ConsoleSMSService()


def get_sms_service() -> SMSService:
    """FastAPI dependency provider for the active SMS service implementation."""
    return _sms_service
