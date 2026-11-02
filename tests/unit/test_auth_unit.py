"""Focused unit tests for authentication without a database or HTTP server."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from src.auth import service as auth_service
from src.auth import utils as auth_utils
from src.auth.models import User
from src.auth.schemas import LoginRequest, RegisterRequest


def _user(*, user_id: int = 7) -> User:
    user = User(
        name="Ishu",
        email="ishu@example.com",
        password="hashed-password",
        credit_balance=50,
    )
    user.id = user_id
    return user


async def test_register_creates_a_user_and_returns_a_token(monkeypatch):
    db = AsyncMock()
    user = _user()
    find_user = AsyncMock(return_value=None)
    create_user = AsyncMock(return_value=user)
    monkeypatch.setattr(auth_service, "find_user_by_email", find_user)
    monkeypatch.setattr(auth_service, "create_user", create_user)
    monkeypatch.setattr(auth_service, "hash_password", lambda _: "hashed-password")
    monkeypatch.setattr(auth_service, "create_access_token", lambda _: "access-token")

    result = await auth_service.AuthService.register_user(
        db,
        RegisterRequest(
            name="Ishu",
            email="ishu@example.com",
            password="plain-password",
        ),
    )

    assert result == {"user": user, "access_token": "access-token"}
    create_user.assert_awaited_once_with(
        db,
        {
            "name": "Ishu",
            "email": "ishu@example.com",
            "password": "hashed-password",
        },
    )
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(user)


async def test_register_rejects_an_existing_email(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(
        auth_service,
        "find_user_by_email",
        AsyncMock(return_value=_user()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth_service.AuthService.register_user(
            db,
            RegisterRequest(
                name="Ishu",
                email="ishu@example.com",
                password="plain-password",
            ),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "User already exists"
    db.commit.assert_not_awaited()


async def test_login_returns_a_token_for_valid_credentials(monkeypatch):
    user = _user()
    monkeypatch.setattr(
        auth_service,
        "find_user_by_email",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(auth_service, "verify_password", lambda *_: True)
    monkeypatch.setattr(auth_service, "create_access_token", lambda _: "access-token")

    result = await auth_service.AuthService.login_user(
        AsyncMock(),
        LoginRequest(email=user.email, password="plain-password"),
    )

    assert result == {"user": user, "access_token": "access-token"}


async def test_login_rejects_unknown_email_and_wrong_password(monkeypatch):
    monkeypatch.setattr(
        auth_service,
        "find_user_by_email",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as missing:
        await auth_service.AuthService.login_user(
            AsyncMock(),
            LoginRequest(email="missing@example.com", password="password"),
        )
    assert missing.value.status_code == 404

    monkeypatch.setattr(
        auth_service,
        "find_user_by_email",
        AsyncMock(return_value=_user()),
    )
    monkeypatch.setattr(auth_service, "verify_password", lambda *_: False)
    with pytest.raises(HTTPException) as invalid:
        await auth_service.AuthService.login_user(
            AsyncMock(),
            LoginRequest(email="ishu@example.com", password="wrong"),
        )
    assert invalid.value.status_code == 400
    assert invalid.value.detail == "Invalid email or password"


def test_access_token_round_trip_contains_user_data(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-0123456789abcdef")
    monkeypatch.setenv("JWT_EXPIRES_MINUTES", "15")

    token = auth_utils.create_access_token(_user())
    payload = auth_utils.decode_access_token(token)

    assert payload["data"]["user"] == {
        "id": 7,
        "name": "Ishu",
        "email": "ishu@example.com",
    }
    assert payload["exp"] > payload["iat"]


def test_access_token_requires_a_persisted_user_id():
    user = _user()
    user.id = None

    with pytest.raises(ValueError, match="User id is required"):
        auth_utils.create_access_token(user)


def test_decode_rejects_invalid_and_expired_tokens(monkeypatch):
    secret = "unit-test-secret-0123456789abcdef"
    monkeypatch.setenv("JWT_SECRET", secret)
    expired = jwt.encode(
        {
            "data": {"user": {"id": 1}},
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        secret,
        algorithm="HS256",
    )

    for token in ("not-a-token", expired):
        with pytest.raises(HTTPException) as exc_info:
            auth_utils.decode_access_token(token)
        assert exc_info.value.status_code == 401


async def test_get_current_user_resolves_the_jwt_user(monkeypatch):
    user = _user()
    monkeypatch.setattr(
        auth_utils,
        "decode_access_token",
        lambda _: {"data": {"user": {"id": user.id}}},
    )
    find_user = AsyncMock(return_value=user)
    monkeypatch.setattr(auth_utils, "find_user_by_id", find_user)

    result = await auth_utils.get_current_user(
        db=AsyncMock(),
        credentials=type("Credentials", (), {"credentials": "token"})(),
    )

    assert result["email"] == "ishu@example.com"
    assert result["credit_balance"] == 50
    find_user.assert_awaited_once()
