from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: int
    name: str
    kind: Literal["company", "client"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["client"] = "client"

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("workspace_name_required")
        return value


class WorkspaceMemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    role: Literal["manager", "member"] = "member"


class WorkspaceMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    user_id: str
    role: Literal["manager", "member"]
