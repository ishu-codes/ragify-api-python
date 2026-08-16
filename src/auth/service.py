from fastapi import HTTPException
from sqlalchemy.ext.asyncio.session import AsyncSession

from .repository import create_user, find_user_by_email
from .schemas import LoginRequest, RegisterRequest
from .utils import create_access_token, hash_password, verify_password


def _invalid_credentials():
    raise HTTPException(status_code=400, detail="Invalid email or password")


class AuthService:
    @staticmethod
    async def register_user(db: AsyncSession, user_info: RegisterRequest):
        existing_user = await find_user_by_email(db, user_info.email)
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")

        hashed_pw = hash_password(user_info.password)
        user = await create_user(
            db,
            {"name": user_info.name, "email": user_info.email, "password": hashed_pw},
        )
        await db.commit()
        await db.refresh(user)

        return {
            "user": user,
            "access_token": create_access_token(user),
        }

    @staticmethod
    async def login_user(db: AsyncSession, user_info: LoginRequest):
        user = await find_user_by_email(db, user_info.email)

        if user is None:
            raise HTTPException(404, detail="User does not exist!")
            # _invalid_credentials()

        if not verify_password(user_info.password, user.password):
            _invalid_credentials()

        return {
            "user": user,
            "access_token": create_access_token(user),
        }
