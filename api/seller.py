"""Seller-facing endpoints (section 2.7).

All endpoints here are authenticated via the seller's JWT session
(`get_current_client_id`) — `client_id` is never trusted from a query param,
form field, or request body.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_client_id
from db.session import get_db
from models.client import Client
from models.conversation import Conversation
from models.post import Post
from models.post_conversation import PostConversation
from schemas.seller import (
    DashboardSummaryResponse,
    PostRegisterRequest,
    PostRegisterResponse,
)

router = APIRouter()
logger = logging.getLogger("seller")


@router.post("/seller/posts", response_model=PostRegisterResponse)
async def register_posts(
    body: PostRegisterRequest,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> PostRegisterResponse:
    """Register the authenticated seller's post tokens.

    Each token is inserted as a `posts` row tagged with the seller's
    `client_id`. Tokens already present (for any client) are left untouched via
    `ON CONFLICT DO NOTHING`. Returns how many were newly registered vs. already
    existed. Tokens repeated within the request body are counted once.
    """
    # De-duplicate within the request body, preserving order. Tokens are already
    # stripped/validated by the schema.
    distinct_tokens = list(dict.fromkeys(body.post_tokens))

    stmt = (
        pg_insert(Post)
        .values([{"post_token": token, "client_id": client_id} for token in distinct_tokens])
        .on_conflict_do_nothing(index_elements=["post_token"])
        .returning(Post.post_token)
    )
    result = await db.execute(stmt)
    inserted = result.scalars().all()
    await db.commit()

    registered = len(inserted)
    already_existed = len(distinct_tokens) - registered

    return PostRegisterResponse(
        registered=registered,
        already_existed=already_existed,
    )


@router.get(
    "/api/v1/seller/dashboard/summary",
    response_model=DashboardSummaryResponse,
)
async def dashboard_summary(
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Lightweight overview counts for the dashboard shell (§3.6, §3.23).

    §3.13 gives NEW seller APIs the `/api/v1/seller/...` prefix; the existing
    `/seller/posts` keeps its established Phase 2 contract. Identity follows
    `/auth/me` semantics (401 when the JWT's client no longer exists). Every
    count filters on the JWT-derived `client_id` — COUNT() only, no rows are
    loaded, and no `client_id` is ever accepted from the browser.
    """
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=401, detail="Client not found")

    async def _count(model: type[Post] | type[Conversation] | type[PostConversation]) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.client_id == client_id)
        )
        return (await db.execute(stmt)).scalar_one()

    return DashboardSummaryResponse(
        phone_number=client.phone_number,
        post_count=await _count(Post),
        conversation_count=await _count(Conversation),
        post_conversation_count=await _count(PostConversation),
    )
