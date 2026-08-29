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
