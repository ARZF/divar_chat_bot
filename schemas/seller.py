"""Request/response schemas for seller-facing endpoints (section 2.7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# `posts.post_token` is String(20) — enforce the same limit here so an
# over-length token fails validation with a clean 422 instead of a raw DB error.
POST_TOKEN_MAX_LENGTH = 20


class PostRegisterRequest(BaseModel):
    """Body for `POST /seller/posts`: a list of the seller's post tokens."""

    post_tokens: list[str] = Field(..., min_length=1)

    @field_validator("post_tokens")
    @classmethod
    def _validate_tokens(cls, tokens: list[str]) -> list[str]:
        cleaned: list[str] = []
        for token in tokens:
            stripped = token.strip()
            if not stripped:
                raise ValueError("post_tokens must not contain blank or whitespace-only entries")
            if len(stripped) > POST_TOKEN_MAX_LENGTH:
                raise ValueError(
                    f"post_token exceeds maximum length of {POST_TOKEN_MAX_LENGTH} characters: {stripped!r}"
                )
            cleaned.append(stripped)
        return cleaned


class PostRegisterResponse(BaseModel):
    """Result of a post-token registration request."""

    registered: int
    already_existed: int


class DashboardSummaryResponse(BaseModel):
    """Seller identity plus lightweight tenant-scoped counts.

    Response of `GET /api/v1/seller/dashboard/summary` (§3.6). Only data that
    already exists — no plan/subscription fields until §3.10 lands.
    """

    phone_number: str | None
    post_count: int
    conversation_count: int
    post_conversation_count: int


class ProductListItem(BaseModel):
    """One seller-facing product row (§3.7.1).

    `normalized_name` and `client_id` are internal — never serialized to the seller.
    """

    id: int
    item_name: str
    price: int
    updated_at: datetime


class ProductListResponse(BaseModel):
    """Paginated product list with the paging metadata the UI needs."""

    items: list[ProductListItem]
    page: int
    page_size: int
    total: int
    page_count: int


class ProductDetailResponse(BaseModel):
    """Single product response — same seller-facing fields as the list item."""

    id: int
    item_name: str
    price: int
    updated_at: datetime
