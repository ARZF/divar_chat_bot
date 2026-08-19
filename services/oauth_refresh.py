# oauth_refresh.py
"""Seller OAuth token refresh, split out of ``services/chatbot.py``."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from db.session import AsyncSessionLocal
from models.oauth_token import OAuthToken
import services.divar as divar_service

logger = logging.getLogger("chatbot")


async def _refresh_supplier_token(client_id: int) -> Optional[str]:
    """Refresh one seller's expired Divar token and return the new access token.

    Divar rotates the refresh token on every call and invalidates the old one, so two
    background tasks refreshing the same seller concurrently would leave whichever pair
    got stored last unusable — that seller could then never refresh again. The row is
    therefore claimed with ``FOR UPDATE`` and the expiry re-checked under that lock, so
    a task that was waiting reuses the winner's token instead of refreshing again.

    Returns ``None`` if the refresh failed, meaning the caller must not send anything.
    """
    async with AsyncSessionLocal() as db:
        oauth_token = (
            await db.execute(
                select(OAuthToken)
                .where(OAuthToken.client_id == client_id)
                .with_for_update()
            )
        ).scalar_one()

        locked_expires_at = oauth_token.token_expires_at
        if locked_expires_at.tzinfo is None:
            locked_expires_at = locked_expires_at.replace(tzinfo=timezone.utc)
        if locked_expires_at > datetime.now(timezone.utc):
            # Another task refreshed this seller while we waited for the lock. Its
            # token is current and it already re-registered the subscription.
            logger.debug(
                "supplier token already refreshed by a concurrent task",
                extra={"client_id": client_id},
            )
            return oauth_token.divar_access_token

        try:
            access_token, refresh_token, expires_in = (
                await divar_service.refresh_access_token(
                    oauth_token.divar_access_token,
                    oauth_token.divar_refresh_token,
                )
            )
        except httpx.HTTPError:
            logger.error(
                "supplier message skipped: OAuth token refresh failed",
                extra={"client_id": client_id},
                exc_info=True,
            )
            return None

        oauth_token.divar_access_token = access_token
        oauth_token.divar_refresh_token = refresh_token
        oauth_token.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in
        )
        await db.commit()

    # Per PHASE2.md §2.9 a subscription is bound to the access token that created it,
    # so it must be re-registered after every refresh or this seller's NEW_MESSAGE
    # events stop arriving with no error surfaced anywhere. Deliberately outside the
    # lock, and non-fatal: the reply this refresh was for should still be sent.
    try:
        await divar_service.register_event_subscription(access_token)
    except httpx.HTTPError:
        logger.warning(
            "event subscription re-registration failed after token refresh",
            extra={"client_id": client_id},
            exc_info=True,
        )

    return access_token
