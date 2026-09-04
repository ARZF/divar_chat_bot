"""Public plans API (§3.10.4, step 28) — read-only catalogue.

No auth: this is the public pricing source. Only active plans are listed;
inactive plans are never represented as available. The endpoint creates
nothing — no subscriptions, no trials, no checkout, no payment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.plan import Plan
from schemas.plans import PlansListResponse

router = APIRouter()


@router.get("/api/v1/plans", response_model=PlansListResponse)
async def list_plans(db: AsyncSession = Depends(get_db)) -> PlansListResponse:
    rows = (
        await db.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.id)
        )
    ).scalars().all()
    return PlansListResponse(items=rows)
