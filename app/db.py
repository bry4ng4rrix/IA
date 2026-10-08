"""Accès base — SQLAlchemy 2.0 asynchrone sur SQLite."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import params


class Base(DeclarativeBase):
    pass


moteur = create_async_engine(params.DATABASE_URL, echo=False, future=True)
Session = async_sessionmaker(moteur, expire_on_commit=False, class_=AsyncSession)


async def creer_tables() -> None:
    from app import models  # noqa: F401 — enregistre les tables

    async with moteur.begin() as cx:
        await cx.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI."""
    async with Session() as session:
        yield session
