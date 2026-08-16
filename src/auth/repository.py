from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

from .models import User


async def find_user_by_id(db: AsyncSession, user_id: int):
    return await db.get(User, user_id)


async def find_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: dict[str, str | int]):
    user = User(**data)
    db.add(user)
    return user
