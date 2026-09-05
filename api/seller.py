"""Seller-facing endpoints (section 2.7).

All endpoints here are authenticated via the seller's JWT session
(`get_current_client_id`) — `client_id` is never trusted from a query param,
form field, or request body.
"""

from __future__ import annotations

import io
import logging

import httpx
import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_client_id
from db.session import get_db
from models.client import Client
from models.conversation import Conversation
from models.post import Post
from models.post_conversation import PostConversation
from models.post_message import PostMessage
from models.product import Product
from schemas.plans import PlanPublicItem, SellerSubscriptionResponse
from schemas.seller import (
    DashboardSummaryResponse,
    ListingAvailabilityUpdateRequest,
    ListingListItem,
    ListingListResponse,
    ListingSyncResponse,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductImportResponse,
    ProductListItem,
    ProductListResponse,
    ProductUpdateRequest,
    SupplierConversationItem,
    SupplierConversationLastMessage,
    SupplierConversationListItem,
    SupplierConversationListResponse,
    SupplierMessageItem,
    SupplierMessageListResponse,
)
from services.divar_listings import sync_listings
from services.subscriptions import (
    effective_subscription_status,
    ensure_default_subscription,
    get_subscription_usage,
)
from services.price_lookup import load_prices_to_db, normalize_text, refresh_lookup_cache

router = APIRouter()
logger = logging.getLogger("seller")

# A 5 MiB xlsx of name/price pairs is tens of thousands of rows — far above
# any real catalog — while bounding pandas parse time and memory (§3.14's
# 413 case; the admin route has no such cap).
IMPORT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


@router.get(
    "/api/v1/seller/dashboard/summary",
    response_model=DashboardSummaryResponse,
)
async def dashboard_summary(
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Lightweight overview counts for the dashboard shell (§3.6, §3.23).

    Identity follows `/auth/me` semantics (401 when the JWT's client no
    longer exists). Every count filters on the JWT-derived `client_id` —
    COUNT() only, no rows are loaded, and no `client_id` is ever accepted
    from the browser.
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


@router.get("/api/v1/seller/listings", response_model=ListingListResponse)
async def list_listings(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ListingListResponse:
    """Paginated, tenant-scoped listing list (§3.8.1, §3.13).

    Reads only what sync already persisted — this endpoint never calls
    Divar: the API's rate limits are per-app (docs/scopes/README.md), so
    syncing on every dashboard read would burn the quota all sellers
    share. Refreshing is the seller's explicit action via
    `POST /api/v1/seller/listings/sync`. An OTP-only seller (no OAuth
    token, never synced) gets an honest empty list, not an error.
    Pagination mirrors the products list (step 15).
    """
    conditions = [Post.client_id == client_id]

    total = (
        await db.execute(select(func.count()).select_from(Post).where(*conditions))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Post)
            .where(*conditions)
            .order_by(Post.created_at.desc(), Post.post_token.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ListingListResponse(
        items=[
            ListingListItem(
                post_token=row.post_token,
                title=row.title,
                category=row.category,
                chat_enabled=row.chat_enabled,
                is_phone_hidden=row.is_phone_hidden,
                is_available=row.is_available,
                present_on_divar=row.present_on_divar,
                last_synced_at=row.last_synced_at,
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        page_count=(total + page_size - 1) // page_size,
    )


@router.post("/api/v1/seller/listings/sync", response_model=ListingSyncResponse)
async def trigger_listing_sync(
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ListingSyncResponse:
    """Refresh the authenticated seller's listings from Divar (step 20's
    `sync_listings`, one user-posts GET per call).

    The explicit counterpart to the read endpoint's read-only design: the
    seller decides when to spend a Divar API call. `skipped` (never
    completed Divar OAuth, or token refresh failed) writes nothing and is
    not an error — the dashboard can show the stale state as-is. A Divar
    outage surfaces as 502 (sync aborted before any write).
    """
    try:
        summary = await sync_listings(db, client_id)
    except httpx.HTTPError:
        logger.warning(
            "seller-triggered listing sync failed",
            extra={"client_id": client_id},
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Divar listing sync failed; listings were not modified",
        )
    if summary is None:
        return ListingSyncResponse(status="skipped")
    return ListingSyncResponse(status="ok", **summary)


@router.patch(
    "/api/v1/seller/listings/{post_token}/availability",
    response_model=ListingListItem,
)
async def update_listing_availability(
    post_token: str,
    body: ListingAvailabilityUpdateRequest,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ListingListItem:
    """Toggle the chatbot on/off for one of the seller's own listings
    (§3.8.4).

    Purely a local flag: this endpoint never calls Divar — `is_available`
    is this project's own chatbot-availability toggle, never touched by
    sync (which maintains the separate `present_on_divar`). The lookup is
    always `post_token AND client_id` — never by token alone — so missing
    and cross-tenant both return the same non-leaking 404 (§3.14).
    """
    listing = (
        await db.execute(
            select(Post).where(
                Post.post_token == post_token, Post.client_id == client_id
            )
        )
    ).scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    listing.is_available = body.is_available
    await db.commit()

    return ListingListItem(
        post_token=listing.post_token,
        title=listing.title,
        category=listing.category,
        chat_enabled=listing.chat_enabled,
        is_phone_hidden=listing.is_phone_hidden,
        is_available=listing.is_available,
        present_on_divar=listing.present_on_divar,
        last_synced_at=listing.last_synced_at,
    )


@router.get("/api/v1/seller/products", response_model=ProductListResponse)
async def list_products(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    """Paginated, tenant-scoped product list (§3.7.1).

    Search mirrors `get_all_matching_prices` semantics but as a DB query: `q`
    is normalized with `normalize_text` and substring-matched against
    `Product.normalized_name`. Ordering is `updated_at DESC, id DESC` (newest
    first, stable tie-break). Every query filters on the JWT-derived
    `client_id` first; the response never exposes `normalized_name`.
    """
    conditions = [Product.client_id == client_id]
    if q:
        normalized_q = normalize_text(q)
        if normalized_q:
            conditions.append(
                Product.normalized_name.contains(normalized_q, autoescape=True)
            )

    total = (
        await db.execute(select(func.count()).select_from(Product).where(*conditions))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Product)
            .where(*conditions)
            .order_by(Product.updated_at.desc(), Product.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ProductListResponse(
        items=[
            ProductListItem(
                id=row.id,
                item_name=row.item_name,
                price=row.price,
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        page_count=(total + page_size - 1) // page_size,
    )


@router.get(
    "/api/v1/seller/products/{product_id}",
    response_model=ProductDetailResponse,
)
async def get_product(
    product_id: int,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    """Single tenant-scoped product lookup (§3.7.1, §3.14).

    The lookup is always `id AND client_id` — never by id alone. Missing and
    cross-tenant both return the same non-leaking 404.
    """
    row = (
        await db.execute(
            select(Product).where(Product.id == product_id, Product.client_id == client_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return ProductDetailResponse(
        id=row.id,
        item_name=row.item_name,
        price=row.price,
        updated_at=row.updated_at,
    )


@router.post(
    "/api/v1/seller/products",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    body: ProductCreateRequest,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    """Create a product for the authenticated seller (§3.7.3, §3.14).

    `normalized_name` is derived server-side via `normalize_text` — never
    trusted from the body. A UNIQUE(client_id, normalized_name) collision is
    a tenant-scoped 409 whose body does not reveal the conflicting product's
    id. The lookup cache is refreshed on every success so chatbot lookups
    see the new row immediately.
    """
    product = Product(
        client_id=client_id,
        item_name=body.item_name,
        normalized_name=normalize_text(body.item_name),
        price=body.price,
    )
    db.add(product)
    try:
        # flush surfaces the UNIQUE violation (and populates id/timestamps)
        # before the commit, so rollback leaves no half-written state.
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A product with this name already exists in your catalog",
        )
    await db.commit()
    await refresh_lookup_cache(db, client_id)

    return ProductDetailResponse(
        id=product.id,
        item_name=product.item_name,
        price=product.price,
        updated_at=product.updated_at,
    )


async def _get_owned_product(
    db: AsyncSession, client_id: int, product_id: int
) -> Product:
    """Fetch a product by id AND client_id, or raise the non-leaking 404.

    Never look up by id alone: missing and cross-tenant are the same 404 (§3.14).
    """
    row = (
        await db.execute(
            select(Product).where(Product.id == product_id, Product.client_id == client_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


@router.patch(
    "/api/v1/seller/products/{product_id}",
    response_model=ProductDetailResponse,
)
async def update_product(
    product_id: int,
    body: ProductUpdateRequest,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    """Update item name and/or price of the seller's own product (§3.7.4).

    A changed item_name re-derives `normalized_name` server-side; the
    UNIQUE(client_id, normalized_name) constraint inherently excludes this
    row's own current pair, so renaming to the same name does not 409.
    `updated_at` is maintained by the model's `onupdate`. Cache is refreshed
    on every success.
    """
    product = await _get_owned_product(db, client_id, product_id)

    if body.item_name is not None:
        product.item_name = body.item_name
        product.normalized_name = normalize_text(body.item_name)
    if body.price is not None:
        product.price = body.price

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A product with this name already exists in your catalog",
        )
    await db.commit()
    await refresh_lookup_cache(db, client_id)

    return ProductDetailResponse(
        id=product.id,
        item_name=product.item_name,
        price=product.price,
        updated_at=product.updated_at,
    )


@router.delete(
    "/api/v1/seller/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_product(
    product_id: int,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete the seller's own product (§3.7.5). 204, no body — matching the
    read endpoints' JSON-only conventions (no confirmation payload). The cache
    is refreshed on every success so chatbot lookups stop matching the row."""
    product = await _get_owned_product(db, client_id, product_id)

    await db.delete(product)
    await db.commit()
    await refresh_lookup_cache(db, client_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/v1/seller/products/import",
    response_model=ProductImportResponse,
)
async def import_products(
    file: UploadFile = File(...),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> ProductImportResponse:
    """Spreadsheet import for the authenticated seller (§3.7.6, §3.14).

    A thin wrapper around the existing `load_prices_to_db` — the
    transactional replace-all (this tenant's rows deleted, the file's rows
    inserted) and the per-tenant cache refresh stay exactly there, unchanged.
    Importing REPLACES the seller's whole catalog by design (maintainer-
    approved). Adds the size cap the admin route lacks; parser and
    schema/content failures are 400s, never 500s.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx files are accepted",
        )

    contents = await file.read()
    if len(contents) > IMPORT_MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 5 MB size limit",
        )

    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        # Untrusted bytes: any parser failure (corrupt zip, wrong format, ...)
        # is a client error, never a 500.
        raise HTTPException(
            status_code=400,
            detail="File is not a readable .xlsx spreadsheet",
        ) from e

    try:
        rows_loaded = await load_prices_to_db(db, client_id, df)
    except (ValueError, AttributeError) as e:
        # ValueError: missing required column (from _parse_df's AttributeError)
        # or content validation failure inside load_prices_to_db.
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. {e}",
        ) from e

    return ProductImportResponse(status="ok", rows_loaded=rows_loaded)


# ---------------------------------------------------------------------------
# Post-conversations (step 24) — supplier-side Divar conversations, read-only
# ---------------------------------------------------------------------------

# A LEFT JOIN condition from PostConversation to its OWNER's posts row,
# riding the JOIN predicate (not the WHERE) so a conversation whose
# post_token is missing or foreign still returns with listing_title=None
# while a title can never be sourced from another tenant's post (§3.14).
def _own_listing_join(client_id: int):
    return and_(
        Post.post_token == PostConversation.post_token,
        Post.client_id == client_id,
    )


@router.get(
    "/api/v1/seller/post-conversations",
    response_model=SupplierConversationListResponse,
)
async def list_post_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> SupplierConversationListResponse:
    """Paginated list of the seller's supplier-side Divar conversations (POST
    system, `post_conversations` table; step 24).

    Every query filters `PostConversation.client_id == client_id` first.
    Each row carries a bounded preview of the latest stored message — one
    extra query, one message per conversation via MAX(id), never the full
    history. Read-only.
    """
    conditions = [PostConversation.client_id == client_id]

    total = (
        await db.execute(
            select(func.count()).select_from(PostConversation).where(*conditions)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(PostConversation, Post.title)
            .outerjoin(Post, _own_listing_join(client_id))
            .where(*conditions)
            .order_by(PostConversation.updated_at.desc(), PostConversation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # Latest stored message per conversation in this page (bounded: at most
    # one PostMessage row per conversation, never the whole history).
    latest: dict[int, PostMessage] = {}
    if rows:
        max_ids = (
            select(
                PostMessage.post_conversation_id,
                func.max(PostMessage.id).label("max_id"),
            )
            .where(
                PostMessage.post_conversation_id.in_(
                    [conv.id for conv, _ in rows]
                )
            )
            .group_by(PostMessage.post_conversation_id)
        ).subquery()
        latest_rows = (
            await db.execute(
                select(PostMessage).join(max_ids, max_ids.c.max_id == PostMessage.id)
            )
        ).scalars().all()
        latest = {pm.post_conversation_id: pm for pm in latest_rows}

    items = []
    for conv, title in rows:
        pm = latest.get(conv.id)
        items.append(
            SupplierConversationListItem(
                conversation_id=conv.divar_conversation_id,
                post_token=conv.post_token,
                listing_title=title,
                current_state=conv.current_state.value,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                last_message=(
                    SupplierConversationLastMessage(
                        sender_type=pm.sender_type.value,
                        text_content=pm.text_content,
                        sent_at=pm.created_at,
                    )
                    if pm is not None
                    else None
                ),
            )
        )

    return SupplierConversationListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        page_count=(total + page_size - 1) // page_size,
    )


@router.get(
    "/api/v1/seller/post-conversations/{conversation_id}",
    response_model=SupplierConversationItem,
)
async def get_post_conversation(
    conversation_id: str,
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> SupplierConversationItem:
    """Single supplier-side Divar conversation (POST system, step 24).

    Lookup is always `divar_conversation_id AND client_id` — cross-tenant
    and nonexistent are the same non-leaking 404 (§3.14).
    """
    row = (
        await db.execute(
            select(PostConversation, Post.title)
            .outerjoin(Post, _own_listing_join(client_id))
            .where(
                PostConversation.client_id == client_id,
                PostConversation.divar_conversation_id == conversation_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv, title = row
    return SupplierConversationItem(
        conversation_id=conv.divar_conversation_id,
        post_token=conv.post_token,
        listing_title=title,
        current_state=conv.current_state.value,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get(
    "/api/v1/seller/post-conversations/{conversation_id}/messages",
    response_model=SupplierMessageListResponse,
)
async def list_post_conversation_messages(
    conversation_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> SupplierMessageListResponse:
    """Paginated, chronological history for ONE supplier-side conversation
    (POST system, step 24).

    The parent is resolved through `post_conversations` with
    `client_id AND divar_conversation_id`, so a cross-tenant conversation is
    the same non-leaking 404 (§3.14) — its messages are never reachable.
    Ordering: `created_at ASC, id ASC`.
    """
    parent = (
        await db.execute(
            select(PostConversation.id).where(
                PostConversation.client_id == client_id,
                PostConversation.divar_conversation_id == conversation_id,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conditions = [PostMessage.post_conversation_id == parent]
    total = (
        await db.execute(
            select(func.count()).select_from(PostMessage).where(*conditions)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(PostMessage)
            .where(*conditions)
            .order_by(PostMessage.created_at.asc(), PostMessage.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return SupplierMessageListResponse(
        items=[
            SupplierMessageItem(
                sender_type=row.sender_type.value,
                text_content=row.text_content,
                sent_at=row.created_at,
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        page_count=(total + page_size - 1) // page_size,
    )


# ---------------------------------------------------------------------------
# Subscription (§3.10.4, step 28) — read-only
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/seller/subscription",
    response_model=SellerSubscriptionResponse,
)
async def get_current_subscription(
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
) -> SellerSubscriptionResponse:
    """The authenticated seller's current subscription (§3.10.4, step 28;
    step 29 adds the derived usage block).

    Owner-scoped by the JWT-derived `client_id` only — a client_id in a
    query param, path, or body is never read. Default Free Trial assignment
    is delegated to the central subscription service (lazy + idempotent):
    a seller with no subscription row gets exactly one trial created here
    on first read; an existing row of any status is returned untouched.
    `status` is the read-time *effective* status: a row stored ACTIVE whose
    `expires_at` has passed is returned as EXPIRED — pure interpretation,
    nothing is mutated on an existing row during the GET. `usage` is the
    step 27 derived count — window-scoped COUNTs over this seller's own
    `post_conversations`/`post_messages` rows, computed read-only by the
    same service; never a stored counter, never enforced here.
    """
    subscription = await ensure_default_subscription(db, client_id)
    await db.commit()  # persist the lazy default assignment, if one happened

    # Async sessions raise MissingGreenlet on lazy relationship access —
    # load the referenced plan explicitly (no-op if already loaded).
    await db.refresh(subscription, ["plan"])
    return SellerSubscriptionResponse(
        status=effective_subscription_status(subscription).value,
        started_at=subscription.started_at,
        expires_at=subscription.expires_at,
        plan=PlanPublicItem.model_validate(subscription.plan),
        usage=await get_subscription_usage(db, subscription),
    )
