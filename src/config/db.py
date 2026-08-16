from collections.abc import AsyncGenerator
from os import getenv

from dotenv import load_dotenv
from fastapi.requests import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()


DATABASE_URL = getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://ragify:ragify@localhost:5432/ragify",
)


class DatabaseManager:
    def __init__(self, url: str = DATABASE_URL):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    def create_session(self) -> AsyncSession:
        return self.session_maker()

    async def connect(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        print("PostgreSQL connected successfully!")

    async def close(self) -> None:
        await self.engine.dispose()


db_manager = DatabaseManager()

engine = db_manager.engine
async_session_maker = db_manager.session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def connect_to_database() -> None:
    await db_manager.connect()


async def close_database_connection() -> None:
    await db_manager.close()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Shared FastAPI dependency to yield a database session per request.
    Expects request.app.state.db_manager to be populated at startup.
    """
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise RuntimeError("DatabaseManager not registered on app.state")

    db: AsyncSession = manager.create_session()
    try:
        yield db
    finally:
        await db.close()
