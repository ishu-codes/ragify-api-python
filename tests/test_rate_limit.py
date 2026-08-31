"""Tests for the PostgreSQL-backed fixed-window rate limiter."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from starlette.requests import Request

from src.auth.models import User
from src.quotas import rate_limit as rl
from src.quotas.models import RateLimit
from src.workspace.models import Workspace


def _make_request(
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] = ("127.0.0.1", 12345),
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "query_string": b"",
            "headers": headers or [],
            "client": client,
            "server": ("testserver", 80),
        }
    )


async def test_increment_counts_within_window(db):
    counts = []
    for _ in range(3):
        counts.append(await rl._increment(db, "register", "ip:1.2.3.4:client:aaa"))
        await db.commit()
    assert counts == [1, 2, 3]


async def test_window_rollover_starts_a_fresh_counter(db):
    key = "ip:1.2.3.4:client:rollover"
    await rl._increment(db, "register", key)
    await db.commit()

    # Rewrite the row so it belongs to a previous window, then increment again:
    # a new window must start counting from one instead of reusing the row.
    await db.execute(
        update(RateLimit)
        .where(RateLimit.key == key)
        .values(window_start=datetime.now(UTC) - timedelta(hours=2))
    )
    await db.commit()

    count = await rl._increment(db, "register", key)
    await db.commit()
    assert count == 1


async def test_enforce_allows_limit_then_raises_429(db):
    key = "ip:9.9.9.9:client:limit"
    for _ in range(5):
        await rl._enforce(db, "register", key)

    with pytest.raises(HTTPException) as excinfo:
        await rl._enforce(db, "register", key)
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"] == "3600"


async def test_rejected_attempts_still_count_toward_the_window(db):
    key = "ip:1.1.1.1:client:blocked"
    for _ in range(5):
        await rl._enforce(db, "register", key)
    with pytest.raises(HTTPException):
        await rl._enforce(db, "register", key)

    result = await db.execute(select(RateLimit.count).where(RateLimit.key == key))
    assert result.scalar_one() == 6


async def test_different_client_ids_on_same_ip_get_separate_buckets(db):
    for _ in range(5):
        await rl._enforce(db, "register", "ip:1.2.3.4:client:aaa")

    # A different client id on the same IP starts a fresh window.
    await rl._enforce(db, "register", "ip:1.2.3.4:client:bbb")


def test_client_ip_prefers_first_forwarded_for_entry():
    request = _make_request(
        headers=[(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")]
    )
    assert rl._client_ip(request) == "203.0.113.5"


def test_client_ip_falls_back_to_peer_address():
    request = _make_request(client=("198.51.100.7", 40000))
    assert rl._client_ip(request) == "198.51.100.7"


def test_client_id_header_is_optional_and_trimmed():
    assert rl._client_id(_make_request()) == ""
    assert (
        rl._client_id(_make_request(headers=[(b"x-client-id", b"  dev-1  ")]))
        == "dev-1"
    )


def test_register_is_rate_limited_per_ip_and_client(client):
    statuses = []
    last: object | None = None
    for i in range(6):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": f"user{i}",
                "email": f"user{i}@example.com",
                "password": "password123",
            },
        )
        statuses.append(response.status_code)
        last = response
    assert statuses == [201, 201, 201, 201, 201, 429]
    assert last.headers["Retry-After"] == "3600"


def test_register_with_different_client_id_gets_a_fresh_bucket(client):
    for i in range(5):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": f"user{i}",
                "email": f"user{i}@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/register",
        headers={"X-Client-ID": "other-device"},
        json={
            "name": "user5",
            "email": "user5@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201


def test_login_is_rate_limited_per_ip_and_client(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "login",
            "email": "login@example.com",
            "password": "password123",
        },
    )

    statuses = []
    for _ in range(11):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "password123"},
        )
        statuses.append(response.status_code)

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


async def test_query_is_rate_limited_after_credits_are_exhausted(client, db):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "query",
            "email": "query@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    user_id = (
        await db.execute(select(User.id).where(User.email == "query@example.com"))
    ).scalar_one()
    workspace = Workspace(user_id=user_id, name="workspace")
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)

    # Zero credits so the query endpoint fails fast with 402 (no RAG call),
    # letting the per-user query rate limit be exercised.
    await db.execute(
        update(User).where(User.id == user_id).values(credit_balance=0)
    )
    await db.commit()

    statuses = []
    for _ in range(11):
        response = client.post(
            f"/api/v1/workspaces/{workspace.id}/query",
            headers=headers,
            json={"query": "hello"},
        )
        statuses.append(response.status_code)

    assert statuses[:10] == [402] * 10
    assert statuses[10] == 429


def test_global_per_user_backstop_blocks_after_burst(monkeypatch, client):
    monkeypatch.setitem(rl.RATE_LIMITS, "api_min", (2, 60))

    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "burst",
            "email": "burst@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    for _ in range(2):
        assert (
            client.get("/api/v1/workspaces/", headers=headers).status_code == 200
        )
    assert client.get("/api/v1/workspaces/", headers=headers).status_code == 429
