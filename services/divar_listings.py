"""Divar listing sync (Phase 3 step 20).

The only module allowed to talk to Divar's listing endpoints. Data comes
from `GET /v1/open-platform/finder/user-posts` (scope `USER_POSTS_GET`,
docs/post/get_user_posts.md) — one request per sync, no per-post
enrichment calls.

`sync_listings` is the sole writer of the Divar-sourced `posts` columns
(title/category/chat_enabled/is_phone_hidden/last_synced_at). A seller's
post tokens enter `posts` only through this flow, which requires a
completed Divar OAuth login: OTP-only sellers have no `oauth_tokens` row,
so their listings are never inserted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import services.divar as divar_service
from models.oauth_token import OAuthToken
from models.post import Post
from services.oauth_refresh import _refresh_supplier_token

logger = logging.getLogger("listings")

USER_POSTS_URL = f"{divar_service.BASE_URL}/v1/open-platform/finder/user-posts"


async def get_user_posts(access_token: str) -> list[dict]:
    """Return the OAuth user's own posts exactly as Divar reports them.

    Raises on HTTP and response-shape failures so a caller can abort the
    sync without touching `posts` — a failed fetch must never look like
    "the seller has no listings".
    """
    response = await divar_service.client.get(
        USER_POSTS_URL, headers=divar_service._oauth_headers(access_token)
    )
    response.raise_for_status()
    payload = response.json()
    posts = payload.get("posts") if isinstance(payload, dict) else None
    if not isinstance(posts, list):
        raise ValueError("user-posts response is missing its 'posts' list")
    return posts


async def sync_listings(db: AsyncSession, client_id: int) -> dict | None:
    """Sync one seller's Divar listings into `posts`.

    Returns ``None`` when the sync could not run (seller never completed
    Divar OAuth, or their token refresh failed) — in that case nothing is
    written. Otherwise returns counts and commits:

    * posts present in the response → inserted (if new) or metadata-
      refreshed, with ``is_available = True``;
    * this seller's posts absent from the response → ``is_available =
      False``. Only rows owned by ``client_id`` are ever touched; a
      post_token already owned by another client is left exactly as it
      is.
    """
    oauth_token = (
        await db.execute(select(OAuthToken).where(OAuthToken.client_id == client_id))
    ).scalar_one_or_none()
    if oauth_token is None:
        logger.info(
            "listing sync skipped: seller has no Divar OAuth token",
            extra={"client_id": client_id},
        )
        return None

    access_token = oauth_token.divar_access_token
    token_expires_at = oauth_token.token_expires_at
    if token_expires_at.tzinfo is None:
        token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)
    if token_expires_at <= datetime.now(timezone.utc):
        access_token = await _refresh_supplier_token(client_id)
        if access_token is None:
            logger.warning(
                "listing sync skipped: OAuth token refresh failed",
                extra={"client_id": client_id},
            )
            return None

    # Any failure here propagates before a single row is written.
    posts = await get_user_posts(access_token)

    # A usable row needs a non-blank token; anything else is skipped.
    by_token: dict[str, dict] = {}
    for post in posts:
        token = post.get("token") if isinstance(post, dict) else None
        if isinstance(token, str) and token.strip():
            by_token[token.strip()] = post
    tokens = list(by_token)
    now = datetime.now(timezone.utc)

    # 1) Absent from this sync → unavailable. Scoped to this client's own
    #    rows; an empty response marks all of them (the seller genuinely
    #    has no listings on Divar).
    unavailable = await db.execute(
        update(Post)
        .where(Post.client_id == client_id, Post.post_token.not_in(tokens))
        .values(is_available=False)
    )

    # 2) Refresh metadata on this seller's already-registered posts.
    own_posts = (
        await db.execute(
            select(Post).where(
                Post.client_id == client_id, Post.post_token.in_(tokens)
            )
        )
    ).scalars().all()
    for post in own_posts:
        data = by_token[post.post_token]
        post.title = data.get("title")
        post.category = data.get("category")
        post.is_phone_hidden = data.get("is_phone_hidden")
        post.chat_enabled = data.get("supplier_chat_assistant_enabled")
        post.is_available = True
        post.last_synced_at = now

    # 3) Insert newly seen tokens (register_posts' ownership pattern:
    #    ON CONFLICT DO NOTHING on the global post_token primary key, so
    #    a token already owned by another client is never stolen).
    registered = 0
    if tokens:
        result = await db.execute(
            pg_insert(Post)
            .values(
                [
                    {
                        "post_token": token,
                        "client_id": client_id,
                        "title": by_token[token].get("title"),
                        "category": by_token[token].get("category"),
                        "is_phone_hidden": by_token[token].get("is_phone_hidden"),
                        "chat_enabled": by_token[token].get(
                            "supplier_chat_assistant_enabled"
                        ),
                        "is_available": True,
                        "last_synced_at": now,
                    }
                    for token in tokens
                ]
            )
            .on_conflict_do_nothing(index_elements=["post_token"])
            .returning(Post.post_token)
        )
        registered = len(result.scalars().all())

    await db.commit()

    summary = {
        "registered": registered,
        "updated": len(own_posts),
        "marked_unavailable": unavailable.rowcount,
    }
    logger.info("listing sync completed", extra={"client_id": client_id, **summary})
    return summary
