from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def create_user(
    session: AsyncSession, username: str, email: str, hashed_password: str
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user