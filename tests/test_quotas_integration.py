"""PostgreSQL integration tests for credits and resource limits."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.auth.models import User
from src.quotas import credits
from src.quotas.models import CreditLedger
from src.workspace.models import Workspace

pytestmark = pytest.mark.integration


async def _create_user(db, email: str = "quota@example.com") -> User:
    user = User(name="Quota", email=email, password="hashed-password")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_spend_credits_is_atomic_and_writes_a_ledger_entry(db):
    user = await _create_user(db)

    spent = await credits.spend_credits(
        db,
        user.id,
        3,
        credits.REASON_QUERY,
        {"workspace_id": 11},
    )
    await db.commit()
    await db.refresh(user)

    assert spent is True
    assert user.credit_balance == 47
    ledger = (
        await db.execute(
            select(CreditLedger)
            .where(CreditLedger.user_id == user.id)
            .order_by(CreditLedger.id.desc())
        )
    ).scalar_one()
    assert ledger.delta == -3
    assert ledger.reason == credits.REASON_QUERY
    assert ledger.details == {"workspace_id": 11}


async def test_spend_credits_returns_false_without_writing_a_debit(db):
    user = await _create_user(db)
    user.credit_balance = 1
    await db.commit()

    spent = await credits.spend_credits(
        db,
        user.id,
        2,
        credits.REASON_UPLOAD,
    )
    await db.commit()
    await db.refresh(user)

    assert spent is False
    assert user.credit_balance == 1
    ledger_count = await db.scalar(
        select(credits.func.count())
        .select_from(CreditLedger)
        .where(CreditLedger.user_id == user.id)
    )
    assert ledger_count == 0


async def test_monthly_balance_resets_lazily_and_is_audited(db):
    user = await _create_user(db)
    user.credit_balance = 0
    user.credit_period_start = datetime.now(UTC) - timedelta(days=40)
    await db.commit()

    balance = await credits.get_balance(db, user.id)
    await db.commit()
    await db.refresh(user)

    assert balance == credits.FREE_MONTHLY_CREDITS
    assert user.credit_balance == credits.FREE_MONTHLY_CREDITS
    ledger = (
        await db.execute(
            select(CreditLedger).where(CreditLedger.user_id == user.id)
        )
    ).scalar_one()
    assert ledger.delta == credits.FREE_MONTHLY_CREDITS
    assert ledger.reason == credits.REASON_MONTHLY_RESET


async def test_refund_restores_credits_and_records_the_reason(db):
    user = await _create_user(db)

    await credits.spend_credits(
        db,
        user.id,
        4,
        credits.REASON_UPLOAD,
    )
    await credits.refund_credits(
        db,
        user.id,
        4,
        {"operation": "failed upload"},
    )
    await db.commit()
    await db.refresh(user)

    assert user.credit_balance == credits.FREE_MONTHLY_CREDITS
    ledger = (
        await db.execute(
            select(CreditLedger)
            .where(CreditLedger.user_id == user.id)
            .order_by(CreditLedger.id)
        )
    ).scalars().all()
    assert [(entry.delta, entry.reason) for entry in ledger] == [
        (-4, credits.REASON_UPLOAD),
        (4, credits.REASON_REFUND),
    ]


async def test_storage_capacity_and_workspace_cap_raise_api_errors(
    db, monkeypatch
):
    user = await _create_user(db, "limits@example.com")
    monkeypatch.setattr(credits, "MAX_STORAGE_BYTES", 10)
    monkeypatch.setattr(credits, "MAX_WORKSPACES", 1)

    with pytest.raises(HTTPException) as storage_error:
        await credits.ensure_storage_capacity(db, user.id, 11)
    assert storage_error.value.status_code == 413

    db.add(Workspace(user_id=user.id, name="Only workspace"))
    await db.commit()
    with pytest.raises(HTTPException) as workspace_error:
        await credits.ensure_workspace_cap(db, user.id)
    assert workspace_error.value.status_code == 409


async def test_storage_usage_accumulates_on_the_workspace(db):
    user = await _create_user(db, "storage@example.com")
    workspace = Workspace(user_id=user.id, name="Storage")
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)

    await credits.add_workspace_storage(db, workspace.id, 120)
    await credits.add_workspace_storage(db, workspace.id, 80)
    await db.commit()
    await db.refresh(workspace)

    assert workspace.storage_bytes == 200
    assert await credits.get_used_storage(db, user.id) == 200
