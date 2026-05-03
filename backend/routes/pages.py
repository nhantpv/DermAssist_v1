"""Page routes — minimal at this TIP. Full page set in TIP-006."""
from fastapi import APIRouter

router = APIRouter(tags=["pages"])


@router.get("/health")
async def health():
    return {"status": "ok"}
