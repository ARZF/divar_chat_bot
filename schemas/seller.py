"""Request/response schemas for seller-facing endpoints (section 2.7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class DashboardSummaryResponse(BaseModel):
    """Seller identity plus lightweight tenant-scoped counts.

    Response of `GET /api/v1/seller/dashboard/summary` (§3.6). Only data that
    already exists — no plan/subscription fields until §3.10 lands.
    """

    phone_number: str | None
    post_count: int
    conversation_count: int
    post_conversation_count: int


class ListingListItem(BaseModel):
    """One seller listing row (§3.8.1/§3.8.3, steps 20-21).

    `client_id` is internal — never serialized. No price/status/url fields:
    unsupported per the step 19 capability matrix. `present_on_divar` is the
    sync's existence verdict; `is_available` is the seller's own chatbot
    toggle (§3.8.4) — two independent flags, never conflated.
    """

    post_token: str
    title: str | None
    category: str | None
    chat_enabled: bool | None
    is_phone_hidden: bool | None
    is_available: bool
    present_on_divar: bool
    last_synced_at: datetime | None


class ListingListResponse(BaseModel):
    """Paginated listing list with the paging metadata the UI needs."""

    items: list[ListingListItem]
    page: int
    page_size: int
    total: int
    page_count: int


class ListingAvailabilityUpdateRequest(BaseModel):
    """Body for `PATCH /api/v1/seller/listings/{post_token}/availability`
    (§3.8.4): the seller's chatbot-on/off toggle for one listing."""

    is_available: bool


class ListingSyncResponse(BaseModel):
    """Result of `POST /api/v1/seller/listings/sync`.

    `status="skipped"` means nothing was written: the seller has never
    completed Divar OAuth (OTP-only) or their token refresh failed.
    """

    status: str
    registered: int = 0
    updated: int = 0
    marked_absent: int = 0


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


class ProductCreateRequest(BaseModel):
    """Body for `POST /api/v1/seller/products` (§3.7.3).

    Only the seller-visible fields are accepted — `normalized_name` is derived
    server-side and `client_id` comes from the JWT, never the body. Length and
    price bounds mirror the `products` columns (String(500), Integer).
    """

    item_name: str = Field(min_length=1, max_length=500)
    price: int = Field(ge=0)


class ProductUpdateRequest(BaseModel):
    """Body for `PATCH /api/v1/seller/products/{product_id}` (§3.7.4).

    Both fields optional, but at least one must be present (422 otherwise).
    """

    item_name: str | None = Field(default=None, min_length=1, max_length=500)
    price: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "ProductUpdateRequest":
        if self.item_name is None and self.price is None:
            raise ValueError("At least one of item_name or price must be provided")
        return self


class ProductImportResponse(BaseModel):
    """Result of `POST /api/v1/seller/products/import` (§3.7.6).

    Same contract meaning as the admin upload (`{"status": "ok",
    "rows_loaded": N}`), kept in the seller schema module so the seller API
    does not depend on schemas/admin.py.
    """

    status: str
    rows_loaded: int


# ---------------------------------------------------------------------------
# Post-conversations (step 24) — supplier-side Divar conversations (the
# seller dashboard's conversation source), read-only
# ---------------------------------------------------------------------------


class SupplierConversationItem(BaseModel):
    """One supplier-side Divar conversation (POST system,
    `post_conversations` table).

    `conversation_id` is the Divar-assigned conversation ID (globally unique)
    — the path identifier on the detail/messages routes; the internal
    database `id` is never exposed. `post_token` is NOT NULL here (the POST
    system always resolves a listing). `current_state` is NEW or ACTIVE.
    """

    conversation_id: str
    post_token: str
    listing_title: str | None
    current_state: str
    created_at: datetime
    updated_at: datetime


class SupplierConversationLastMessage(BaseModel):
    """Preview of the most recent supplier-side message (list rows only)."""

    sender_type: str
    text_content: str | None
    sent_at: datetime


class SupplierConversationListItem(SupplierConversationItem):
    """Supplier conversation list row — item fields plus a bounded preview
    of the latest stored message, when one exists."""

    last_message: SupplierConversationLastMessage | None


class SupplierConversationListResponse(BaseModel):
    """Paginated POST-system conversation list with paging metadata."""

    items: list[SupplierConversationListItem]
    page: int
    page_size: int
    total: int
    page_count: int


class SupplierMessageItem(BaseModel):
    """One supplier-side message (POST system, `post_messages` table).

    Only safe fields are exposed: sender type (buyer/bot), text, and
    timestamp.
    """

    sender_type: str
    text_content: str | None
    sent_at: datetime


class SupplierMessageListResponse(BaseModel):
    """Paginated, chronological POST-system message history."""

    items: list[SupplierMessageItem]
    page: int
    page_size: int
    total: int
    page_count: int
