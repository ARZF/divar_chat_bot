import io
import logging

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_client_id
from db.session import get_db
from schemas.admin import UploadPricesResponse
from services import price_lookup

router = APIRouter()
logger = logging.getLogger("admin")


@router.post("/admin/upload-prices", response_model=UploadPricesResponse)
async def upload_prices(
    file: UploadFile = File(...),
    client_id: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped price upload (2.7).

    `client_id` is resolved from the authenticated seller's JWT
    (`get_current_client_id`) — never from a query param or request body. The
    upload is a transactional replace of *only* this client's products, after
    which the per-tenant lookup cache is refreshed (both handled by
    `price_lookup.load_prices_to_db`).
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx files are accepted",
        )

    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    try:
        rows_loaded = await price_lookup.load_prices_to_db(db, client_id, df)
    except AttributeError as e:
        # `_parse_df` uses itertuples() attribute access, so a missing "price"
        # or "product" column raises AttributeError (not KeyError) — confirmed
        # 2026-07-21. Surface it as a clean 400 instead of a raw 500.
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Missing required column: {e}",
        ) from e

    return UploadPricesResponse(
        status="ok",
        rows_loaded=rows_loaded,
    )
