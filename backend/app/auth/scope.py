"""Kund-scoping helpers for authenticated users."""

from __future__ import annotations

from fastapi import HTTPException

from app.database.models import UserAccount


def assert_kund_access(user: UserAccount, customer_id: int | None) -> None:
    """Admin passes; user/bolag must match kund_id. Missing customer_id is 403 for non-admin."""
    if user.role == "admin":
        return
    if customer_id is None or user.kund_id is None or customer_id != user.kund_id:
        raise HTTPException(status_code=403, detail="kund_access_denied")


def effective_customer_id(
    user: UserAccount,
    requested: int | None = None,
) -> int | None:
    """
    Resolve list-filter customer_id.

    Admin: optional requested filter (None = all).
    Non-admin: always their kund_id (ignore client override).
    """
    if user.role == "admin":
        return requested
    if user.kund_id is None:
        raise HTTPException(status_code=403, detail="kund_access_denied")
    return user.kund_id


def require_user_kund_id(user: UserAccount) -> int:
    """Customer id for creates by non-admin; admin callers should pass explicitly."""
    if user.kund_id is None:
        raise HTTPException(status_code=403, detail="kund_access_denied")
    return user.kund_id
