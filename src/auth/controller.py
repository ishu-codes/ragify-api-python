from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.db import get_session
from .schemas import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserInfo,
)
from .service import AuthService
from .utils import authenticated_user, require_auth

router = APIRouter()


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_session)):
    return await AuthService.register_user(db, payload)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_session)):
    return await AuthService.login_user(db, payload)


@router.get("/session", response_model=UserInfo, dependencies=[Depends(require_auth)])
async def session(request: Request):
    return authenticated_user(request)
