"""Monthly credit pool plus storage and workspace caps.

All writes happen inside the caller's transaction: a successful spend is only
committed when the request succeeds, and a failed request rolls back the debit
(i.e. failed queries/upload attempts cost nothing).
"""

from datetime import UTC, datetime
from math import ceil

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio.session import AsyncSession

from ..auth.models import User
from ..workspace.models import Workspace
from .config import (
    FREE_MONTHLY_CREDITS,
    MAX_STORAGE_BYTES,
    MAX_WORKSPACES,
    QUERY_CREDIT_COST,
    UPLOAD_CREDIT_STRIDE_BYTES,
)
from .models import CreditLedger

REASON_MONTHLY_RESET = "monthly_reset"
REASON_QUERY = "query"
REASON_UPLOAD = "upload"
REASON_REFUND = "refund"


def _log(db: AsyncSession, user_id: int, delta: int, reason: str, details: dict) -> None:
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=delta,
            reason=reason,
            details=details or {},
        )
    )


async def _refresh_credits_if_needed(db: AsyncSession, user_id: int) -> int:
    """Lazily reset the monthly pool on the first request of a new month."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            func.date_trunc("month", User.credit_period_start)
            < func.date_trunc("month", now),
        )
        .values(credit_balance=FREE_MONTHLY_CREDITS, credit_period_start=now)
        .returning(User.credit_balance)
    )
    balance = result.scalar_one_or_none()
    if balance is not None:
        _log(
            db,
            user_id,
            FREE_MONTHLY_CREDITS,
            REASON_MONTHLY_RESET,
            {"balance": FREE_MONTHLY_CREDITS},
        )
        return balance

    current = await db.scalar(select(User.credit_balance).where(User.id == user_id))
    return current or 0


async def get_balance(db: AsyncSession, user_id: int) -> int:
    return await _refresh_credits_if_needed(db, user_id)


async def spend_credits(
    db: AsyncSession,
    user_id: int,
    cost: int,
    reason: str,
    details: dict | None = None,
) -> bool:
    """Atomically debit `cost` credits; returns False when balance is too low."""
    if cost <= 0:
        return True

    await _refresh_credits_if_needed(db, user_id)
    result = await db.execute(
        update(User)
        .where(User.id == user_id, User.credit_balance >= cost)
        .values(credit_balance=User.credit_balance - cost)
        .returning(User.credit_balance)
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        return False

    _log(db, user_id, -cost, reason, details or {})
    return True


async def refund_credits(
    db: AsyncSession,
    user_id: int,
    cost: int,
    details: dict | None = None,
) -> None:
    """Restore credits after a failed operation (e.g. an aborted query)."""
    if cost <= 0:
        return
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credit_balance=User.credit_balance + cost)
    )
    _log(db, user_id, cost, REASON_REFUND, details or {})


def upload_credit_cost(total_bytes: int) -> int:
    """Upload cost: 1 credit per stride (default 5 MiB), min 1 per upload."""
    if total_bytes <= 0:
        return 1
    return max(1, ceil(total_bytes / UPLOAD_CREDIT_STRIDE_BYTES))


async def get_used_storage(db: AsyncSession, user_id: int) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(Workspace.storage_bytes), 0)).where(
            Workspace.user_id == user_id
        )
    )
    return int(total or 0)


async def ensure_storage_capacity(
    db: AsyncSession, user_id: int, additional_bytes: int
) -> None:
    used = await get_used_storage(db, user_id)
    if used + additional_bytes > MAX_STORAGE_BYTES:
        remaining = max(0, MAX_STORAGE_BYTES - used)
        raise HTTPException(
            status_code=413,
            detail=(
                f"Storage limit reached: {used // (1024 * 1024)} MiB of "
                f"{MAX_STORAGE_BYTES // (1024 * 1024)} MiB used. "
                f"Free up space or upload at most {remaining // (1024 * 1024)} MiB more."
            ),
        )


async def ensure_workspace_cap(db: AsyncSession, user_id: int) -> None:
    count = await db.scalar(
        select(func.count()).select_from(Workspace).where(Workspace.user_id == user_id)
    )
    if (count or 0) >= MAX_WORKSPACES:
        raise HTTPException(
            status_code=409,
            detail=f"The free plan allows up to {MAX_WORKSPACES} workspaces.",
        )


async def add_workspace_storage(
    db: AsyncSession, workspace_id: int, additional_bytes: int
) -> None:
    await db.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(storage_bytes=Workspace.storage_bytes + additional_bytes)
    )


async def require_query_credit(db: AsyncSession, user_id: int, workspace_id: int) -> None:
    if not await spend_credits(
        db,
        user_id,
        QUERY_CREDIT_COST,
        REASON_QUERY,
        {"workspace_id": workspace_id},
    ):
        raise HTTPException(
            status_code=402,
            detail=(
                "You've used all your free credits for this month. "
                "Credits reset on the 1st."
            ),
        )
