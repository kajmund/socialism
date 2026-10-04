"""Recognize flushed writes before a borrowed input session may be released."""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_WRITES = "transaction_has_writes"


@event.listens_for(Session, "after_flush")
def _remember_flush(session: Session, _context) -> None:
    session.info[_WRITES] = True


@event.listens_for(Session, "do_orm_execute")
def _remember_statement(state) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        state.session.info[_WRITES] = True


@event.listens_for(Session, "after_transaction_end")
def _clear_transaction(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(_WRITES, None)


def has_pending_writes(session: AsyncSession) -> bool:
    return bool(session.new or session.dirty or session.deleted or session.info.get(_WRITES))
