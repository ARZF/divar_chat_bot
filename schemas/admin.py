from pydantic import BaseModel


class UploadPricesResponse(BaseModel):
    status: str
    rows_loaded: int