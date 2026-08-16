from datetime import UTC, datetime, timedelta
from os import getenv

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio.session import AsyncSession

from apps.api.src.auth.models import User
from apps.api.src.config.db import get_session

# from src.auth.schemas import UserDto
from .repository import find_user_by_id
from .serializer import serialize_user

load_dotenv()

bearer_scheme = HTTPBearer()


def _get_jwt_secret() -> str:
    secret = getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")
    return secret


def create_access_token(user: User, expires_minutes: int | None = None) -> str:
    ttl_minutes = expires_minutes or int(getenv("JWT_EXPIRES_MINUTES", "60"))
    now = datetime.now(UTC)

    if user.id is None:
        raise ValueError("User id is required to create an access token")

    payload = {
        "data": {
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
            }
        },
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, str | int]:
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


async def get_current_user(
    db: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("data", {}).get("user", {}).get("id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await find_user_by_id(db, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")

    return serialize_user(user)


async def require_auth(
    request: Request,
    current_user: dict[str, str | int] = Depends(get_current_user),
):
    request.state.user = current_user
    return current_user


def authenticated_user(request: Request) -> dict[str, str | int]:
    user = getattr(request.state, "user", None)

    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return user


def get_current_user_id(request: Request) -> int:
    """Dependency that returns the authenticated user's id."""
    return int(authenticated_user(request)["id"])
