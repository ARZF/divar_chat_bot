import hmac, io

import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from services import price_lookup
from schemas.admin import UploadPricesResponse

router = APIRouter()
bearer = HTTPBearer()


@router.post("/admin/upload-prices", response_model=UploadPricesResponse)
async def upload_prices(
    credentials: HTTPAuthorizationCredentials = bearer,
    file: UploadFile = File(...),
):
    if not hmac.compare_digest(credentials.credentials, settings.admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    price_lookup.load_prices_from_df(df)

    return UploadPricesResponse(status="ok", rows_loaded=len(df))
