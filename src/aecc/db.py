"""SQLite engine/session helpers with required V1 pragmas.

Required behaviors (spec section 13):
  * foreign-key enforcement ON;
  * WAL mode for file-backed databases;
  * bounded busy timeout;
  * the immutability triggers required by the domain (created by migration).
"""

from __future__ import annotations

from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from aecc.models import Base

BUSY_TIMEOUT_MS = 5000


def _connect_configure(dbapi_connection, connection_record):  # noqa: ANN001, ANN202
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL is meaningful for file-backed databases; for :memory: SQLite
        # keeps 'memory' mode and returns it — callers must not treat that as failure.
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def apply_sqlite_pragmas(engine: Engine) -> Engine:
    """Attach pragma configuration to an engine (idempotent)."""
    event.listen(engine, "connect", _connect_configure)
    # Apply to any already-open pooled connections by opening one now.
    with engine.connect() as conn:
        conn.execute(text(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        try:
            conn.execute(text("PRAGMA journal_mode=WAL"))
        except Exception:
            pass
        conn.commit()
    return engine


def create_engine_for_path(path: str | Path, *, echo: bool = False) -> Engine:
    """Create a SQLite engine for a file path with V1 pragmas enabled."""
    db_path = Path(path)
    if str(db_path) != ":memory:" and db_path.parent and str(db_path.parent) not in ("", "."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=echo, future=True)
    return apply_sqlite_pragmas(engine)


def create_memory_engine(*, echo: bool = False) -> Engine:
    engine = create_engine("sqlite:///:memory:", echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _mem_pragmas(dbapi_connection, connection_record):  # noqa: ANN202
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
