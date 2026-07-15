import logging
import os
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, ConflictError
from app.models import User
from app.schemas import UserCreate, UserLogin, UserRead
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token_str,
    decode_token,
    get_password_hash,
    get_user,
    get_user_by_id,
    revoke_access_token,
    rotate_refresh_token,
    store_refresh_token,
)
from app.services.user_service import create_user
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


redis = aioredis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True
)
router = APIRouter()


# --- Current User Dependency ---


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_token(token, secret=SECRET_KEY, algorithm=ALGORITHM)
    if payload is None:
        raise AuthenticationError("Invalid token")
    user_id = uuid.UUID(payload["sub"])
    jti = payload["jti"]

    if await redis.get(f"blacklist:{jti}"):
        raise AuthenticationError("Token revoked")

    user = await get_user_by_id(session, user_id)
    if not user:
        raise AuthenticationError("User not found")
    return user


TokenDep = Annotated[User, Depends(get_current_user)]


# --- Routes ---


@router.post("/register", response_model=UserRead)
async def register(
    user_data: UserCreate,
    session: AsyncSession = Depends(get_db),
):
    existing_user = await get_user(session, user_data.username)
    if existing_user:
        raise ConflictError("Username already taken")

    existing_email = await session.execute(
        select(User).where(User.email == user_data.email)
    )
    if existing_email.scalar_one_or_none():
        raise ConflictError("Email already registered")

    user = await create_user(
        session,
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
    )
    return user


@router.post("/token")
async def login(
    response: Response,
    creds: UserLogin,
    session: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(session, creds.username, creds.password)
    if not user:
        raise AuthenticationError("Incorrect credentials")

    access_token = create_access_token(
        user.id,
        secret=SECRET_KEY,
        algorithm=ALGORITHM,
        expire_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    refresh_token_str = create_refresh_token_str()
    await store_refresh_token(
        redis,
        refresh_token_str,
        user.id,
        expire_days=REFRESH_TOKEN_EXPIRE_DAYS,
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return {"message": "logged in"}


@router.post("/token/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    old_refresh_token = request.cookies.get("refresh_token")
    if not old_refresh_token:
        raise AuthenticationError("No refresh token")

    user_id = await redis.get(f"refresh:{old_refresh_token}")
    if not user_id:
        raise AuthenticationError("Invalid or expired refresh token")

    user = await get_user_by_id(session, uuid.UUID(str(user_id)))
    if not user:
        raise AuthenticationError("User not found")

    new_refresh_str = await rotate_refresh_token(
        redis,
        old_refresh_token,
        user.id,
        expire_days=REFRESH_TOKEN_EXPIRE_DAYS,
    )

    response.set_cookie(
        key="access_token",
        value=create_access_token(
            user.id,
            secret=SECRET_KEY,
            algorithm=ALGORITHM,
            expire_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
        ),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_str,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return {"message": "token refreshed"}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("access_token")
    if token:
        payload = decode_token(token, secret=SECRET_KEY, algorithm=ALGORITHM)
        if payload and payload.get("exp"):
            await revoke_access_token(redis, payload["jti"], payload["exp"])

    refresh_token_str = request.cookies.get("refresh_token")
    if refresh_token_str:
        await redis.delete(f"refresh:{refresh_token_str}")

    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "logged out"}


@router.get("/users/me/", response_model=UserRead)
async def read_me(current_user: TokenDep):
    return current_user