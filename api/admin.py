import hmac
import io
import logging

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.session import get_db
from schemas.admin import UploadPricesResponse
from services import price_lookup

router = APIRouter()
bearer = HTTPBearer()
logger = logging.getLogger("admin")


@router.post("/admin/upload-prices", response_model=UploadPricesResponse)
async def upload_prices(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    # TODO (2.7): replace client_id query param with get_current_client_id() JWT dependency
    client_id: int = Query(..., description="Seller client ID (temporary — replaced by JWT in 2.7)"),
    db: AsyncSession = Depends(get_db),
):
    if not hmac.compare_digest(
        credentials.credentials,
        settings.admin_token,
    ):
        raise HTTPException(401, "Unauthorized")

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx files are accepted",
        )

    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    try:
        rows_loaded = await price_lookup.load_prices_to_db(db, client_id, df)
    except KeyError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Missing required column: {e}",
        ) from e

    return UploadPricesResponse(
        status="ok",
        rows_loaded=rows_loaded,
    )
