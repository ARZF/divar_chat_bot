"""Seller-facing endpoints (section 2.7).

All endpoints here are authenticated via the seller's JWT session
(`get_current_client_id`) — `client_id` is never trusted from a query param,
form field, or request body.
"""

from __future__ import annotations

import io
import logging

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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_client_id
from db.session import get_db
from models.client import Client
from models.conversation import Conversation
from models.post import Post
from models.post_conversation import PostConversation
from models.product import Product
from schemas.seller import (
    DashboardSummaryResponse,
    PostRegisterRequest,
    PostRegisterResponse,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductImportResponse,
    ProductListItem,
    ProductListResponse,
    ProductUpdateRequest,
)
from services.price_lookup import load_prices_to_db, normalize_text, refresh_lookup_cache

router = APIRouter()
logger = logging.getLogger("seller")

# A 5 MiB xlsx of name/price pairs is tens of thousands of rows — far above
# any real catalog — while bounding pandas parse time and memory (§3.14's
# 413 case; the admin route has no such cap).
IMPORT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


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
