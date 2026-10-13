"""Optional single-host cross-process serialization for sandbox/local deployments.

This is NOT a distributed/production lease. Use a host-managed database lock or
fenced lease spanning every worker for production, and reconcile ambiguous actions.
"""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import asyncio
import sqlite3
from typing import Iterator


class LeaseUnavailable(RuntimeError):
    """A dispatch lock could not be acquired. No tool may run."""


class LocalSqliteDispatchLease:
    """Single-host, cross-process transaction lock for development and tests.

    Every bridge worker MUST share the exact same database on a local filesystem.
    Uses SQLite BEGIN IMMEDIATE and holds the transaction until callback completion.
    This serializes ALL operations (not one row per decision); it is unsuitable for
    network shares, distributed hosts, or high-throughput production dispatch.
    """

    def __init__(self, database: str | Path, *, timeout: float = 8.0):
        path = Path(database).expanduser()
        if not path.is_absolute() or str(path) == ":memory:":
            raise ValueError("A shared absolute local SQLite file path is required")
        if not 0 < timeout <= 60:
            raise ValueError("Invalid SQLite lock timeout")
        self.database = str(path)
        self.timeout = timeout

    @contextmanager
    def __call__(self, operation_key: str) -> Iterator[None]:
        if not isinstance(operation_key, str) or not operation_key.startswith("lg-langchain-"):
            raise ValueError("Invalid dispatch operation key")
        conn = None
        try:
            conn = sqlite3.connect(self.database, timeout=self.timeout, isolation_level=None)
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            if conn is not None:
                conn.close()
            raise LeaseUnavailable("Local dispatch lease unavailable") from None
        try:
            yield
        finally:
            try:
                conn.rollback()  # release write lock; no business data stored
            finally:
                conn.close()


class LocalAsyncSqliteDispatchLease(LocalSqliteDispatchLease):
    """Single-host async counterpart using the SAME local SQLite file.

    Uses non-blocking immediate lock attempts (no wait in the event loop).
    Disposed on cancellation. Do not use on network shares or distributed hosts.
    """
    @asynccontextmanager
    async def __call__(self, operation_key: str):
        if not isinstance(operation_key, str) or not operation_key.startswith("lg-langchain-"):
            raise ValueError("Invalid dispatch operation key")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        conn = None
        while True:
            try:
                conn = sqlite3.connect(self.database, timeout=0, isolation_level=None)
                conn.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.Error:
                if conn is not None:
                    conn.close()
                    conn = None
                if loop.time() >= deadline:
                    raise LeaseUnavailable("Local async dispatch lease unavailable") from None
                await asyncio.sleep(0.025)
        try:
            yield
        finally:
            try:
                conn.rollback()
            finally:
                conn.close()
