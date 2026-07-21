# pyrefly: ignore [missing-import]
from fastapi import APIRouter

router = APIRouter()


@router.get("/live")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness():
    """Extend this to actually ping Postgres/Redis/Chroma/RabbitMQ before
    reporting ready — kept minimal here so it doesn't hide behind
    infra that may not be running in a given environment."""
    return {"status": "ok"}
