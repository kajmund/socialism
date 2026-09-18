"""Customer / project scoping schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


from app.schemas.profiles import OrganizationFields


class ProjektOut(BaseModel):
    id: int
    customer_id: int
    name: str
    slug: str


class KundOut(OrganizationFields):
    id: int
    name: str
    slug: str
    product: str | None = None
    available_modules: list[str] = Field(default_factory=list)
    projekt: list[ProjektOut] = Field(default_factory=list)


class KundCreate(OrganizationFields):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64)
    product: str | None = None
    available_modules: list[str] = Field(default_factory=list)


class KundUpdate(OrganizationFields):
    product: str | None = None
    available_modules: list[str] | None = None


class ProjektCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64)
