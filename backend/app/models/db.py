"""
Async SQLAlchemy engine/session setup. Import `get_db` as a FastAPI
dependency in any router that touches Postgres.
"""
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
