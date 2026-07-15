from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    email: str
    accounts: list[AccountRead] = []


class AccountCreate(BaseModel):
    name: str


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user: UserRead
    name: str
    balance: float
    disabled: bool
    last_version: int
    created_at: str
    updated_at: str
    events: list[EventRead] = []


class EventCreate(BaseModel):
    event_type: str
    data: dict


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account: AccountRead
    event_type: str
    data: dict
    version: int
    created_at: str

# Resolve circular forward references
UserRead.model_rebuild()
AccountRead.model_rebuild()
EventRead.model_rebuild()
