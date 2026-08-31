"""Admin user-account management schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

UserRole = Literal["admin", "user", "bolag"]


class MeOut(BaseModel):
    id: str
    email: str
    role: UserRole
    kund_id: int | None
    kund_slug: str | None
    available_modules: list[str]


class UserAccountOut(BaseModel):
    id: str
    email: str
    role: UserRole
    kund_id: int | None
    kund_name: str | None = None
    invited_at: datetime
    last_seen_at: datetime | None = None


class UserInviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: UserRole
    kund_id: int | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("invalid email")
        return email

    @model_validator(mode="after")
    def validate_role_kund(self) -> UserInviteRequest:
        if self.role == "admin":
            if self.kund_id is not None:
                raise ValueError("admin must not have kund_id")
        elif self.kund_id is None:
            raise ValueError(f"{self.role} requires kund_id")
        return self


class UserAccountUpdate(BaseModel):
    role: UserRole | None = None
    kund_id: int | None = None
