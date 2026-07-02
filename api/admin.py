import hmac, io
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from services import price_lookup
from schemas.admin import UploadPricesResponse

router = APIRouter()
bearer = HTTPBearer()

@router.post("/admin/upload-prices", response_model=UploadPricesResponse)
async def upload_prices(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
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
        price_lookup.load_prices_from_df(df)
    except KeyError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Missing required column: {e}",
        ) from e

    return UploadPricesResponse(
        status="ok",
        rows_loaded=len(df),
    )