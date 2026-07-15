import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

password_hash = PasswordHash.recommended()


def verify_password(plain: str, hashed: str) -> bool:
    return password_hash.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


async def get_user(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> User | None:
    user = await get_user(session, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(
    user_id: uuid.UUID,
    *,
    secret: str,
    algorithm: str = "HS256",
    expire_minutes: int = 30,
) -> str:
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "jti": jti},
        secret,
        algorithm=algorithm,
    )


def create_refresh_token_str() -> str:
    return str(uuid.uuid4())


async def store_refresh_token(
    redis: Redis, token: str, user_id: uuid.UUID, expire_days: int = 7
) -> None:
    await redis.setex(f"refresh:{token}", expire_days * 86400, str(user_id))


async def rotate_refresh_token(
    redis: Redis, old_token: str, user_id: uuid.UUID, expire_days: int = 7
) -> str:
    await redis.delete(f"refresh:{old_token}")
    new_token = create_refresh_token_str()
    await store_refresh_token(redis, new_token, user_id, expire_days)
    return new_token


def decode_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except InvalidTokenError:
        return None

    sub = payload.get("sub")
    jti = payload.get("jti")
    if not sub or not jti:
        return None

    try:
        uuid.UUID(sub)
    except ValueError:
        return None
    except TypeError:
        return None

    return payload


async def revoke_access_token(redis: Redis, jti: str, exp: int) -> None:
    ttl = int(exp) - int(datetime.now(timezone.utc).timestamp())
    if ttl > 0:
        await redis.setex(f"blacklist:{jti}", ttl, "1")