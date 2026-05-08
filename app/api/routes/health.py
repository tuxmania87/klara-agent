"""Health check endpoint."""
from fastapi import APIRouter
from app.database import engine

router = APIRouter()


@router.get("")
async def health() -> dict:
    return {"status": "ok", "service": "personal-ai-agent"}


@router.get("/db")
async def health_db() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}
