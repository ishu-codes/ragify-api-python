"""Fixed-window rate limiting backed by PostgreSQL.

Identity keys:
  - authenticated routes: ``user:{id}`` (authoritative; from the JWT)
  - anonymous routes (register/login): ``ip:{xff}:client:{x-client-id}``
    where the IP is the first X-Forwarded-For entry set by the proxy and the
    client id is an optional opaque UUID supplied by the browser.

The client id is a soft signal to reduce false positives behind shared IPs
(NAT/CGNAT); it is deliberately not used on its own for any decision.
"""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession

from ..auth.utils import get_current_user_id
from ..config.db import get_session
from .config import RATE_LIMITS
from .models import RateLimit

# Rows older than this are removed opportunistically on write.
_CLEANUP_AGE_SECONDS = 2 * 24 * 60 * 60


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _client_id(request: Request) -> str:
    return (request.headers.get("x-client-id") or "").strip()


def _window_start(window_seconds: int) -> datetime:
    now = datetime.now(UTC)
    return datetime.fromtimestamp(
        (now.timestamp() // window_seconds) * window_seconds, tz=UTC
    )


async def _increment(db: AsyncSession, bucket: str, key: str) -> int:
    """Atomically increment the fixed-window counter and return the new count."""
    limit, window = RATE_LIMITS[bucket]
    result = await db.execute(
        insert(RateLimit)
        .values(bucket=bucket, key=key, window_start=_window_start(window), count=1)
        .on_conflict_do_update(
            index_elements=[RateLimit.bucket, RateLimit.key, RateLimit.window_start],
            set_={"count": RateLimit.count + 1},
        )
        .returning(RateLimit.count)
    )
    count = result.scalar_one()

    # Opportunistic cleanup keeps the table small at this scale.
    stale_before = datetime.fromtimestamp(
        datetime.now(UTC).timestamp() - _CLEANUP_AGE_SECONDS, tz=UTC
    )
    await db.execute(delete(RateLimit).where(RateLimit.window_start < stale_before))
    return count


async def _enforce(db: AsyncSession, bucket: str, key: str) -> None:
    limit, window = RATE_LIMITS[bucket]
    count = await _increment(db, bucket, key)
    # Commit the counter even when the request is rejected, so blocked
    # attempts still count toward the window.
    await db.commit()
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(window)},
        )


def rate_limit_authenticated(bucket: str):
    """FastAPI dependency: rate limit keyed by the authenticated user id."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_session),
        user_id: int = Depends(get_current_user_id),
    ) -> None:
        await _enforce(db, bucket, f"user:{user_id}")

    return _check


def rate_limit_anonymous(bucket: str):
    """FastAPI dependency: rate limit keyed by IP + optional client id."""

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_session),
    ) -> None:
        key = f"ip:{_client_ip(request)}:client:{_client_id(request)}"
        await _enforce(db, bucket, key)

    return _check
