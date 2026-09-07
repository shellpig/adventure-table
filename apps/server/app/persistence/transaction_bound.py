from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy.engine import Connection


class TransactionBoundEngine:
    """Present one existing Connection through the small Engine surface core repos use.

    Character persistence predates P2 and intentionally owns its public transactions.
    Room workflows need those exact algorithms to participate in a larger Web-only
    transaction without teaching Character Core about Room. Binding begin()/connect()
    to an already-open Connection preserves the existing repository code while the
    outer caller remains the only commit/rollback owner.
    """

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        yield self.connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        yield self.connection


__all__ = ["TransactionBoundEngine"]
