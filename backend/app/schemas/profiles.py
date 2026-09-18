"""Editable profile fields. Unknown fields, including privileges, are rejected."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = (
        None
    )
    last_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = (
        None
    )
    job_title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )


class OrganizationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None
    organization_number: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None
    ) = None
    address_line1: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None
    address_line2: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None
    postal_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = (
        None
    )
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    country_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2)] | None = (
        None
    )


PROFILE_FIELDS = tuple(ProfileFields.model_fields)
ORGANIZATION_FIELDS = tuple(OrganizationFields.model_fields)
