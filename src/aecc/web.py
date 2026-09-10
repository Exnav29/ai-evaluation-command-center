"""Operator Dashboard V1: FastAPI application entry point.

Server-rendered HTML (Jinja2) over the Phase 2 SQLite/SQLAlchemy evidence
foundation. Routes:

- GET /operator — overview with summary cards + recent runs table
- GET /operator/runs/{run_id} — evidence-oriented run detail (404 when missing)
- GET /operator/qualifications — one row per harness+model+capability triple

The app queries persisted evidence per request; no hard-coded rows.
``create_app(engine=...)`` accepts an explicit engine so tests can bind an
isolated migrated SQLite database. Without an argument the app resolves the
database from ``AECC_DB_PATH`` (default ``data/evaluations.sqlite``) and
runs pending Alembic migrations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from aecc import dashboard_queries as queries
from aecc import dashboard_viewmodels as vm

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _default_db_path() -> Path:
    override = os.environ.get("AECC_DB_PATH")
    if override:
        return Path(override)
    # Repository root is two levels above src/aecc (src/.. = repo when installed
    # as a package; fall back to cwd otherwise).
    root = HERE.parents[2] if len(HERE.parents) >= 3 else Path.cwd()
    candidate = root / "data" / "evaluations.sqlite"
    if candidate.parent.exists() or root.name != "/":
        return candidate
    return Path.cwd() / "data" / "evaluations.sqlite"


def _ensure_migrated(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    root = HERE.parents[2] if len(HERE.parents) >= 3 else Path.cwd()
    ini = root / "alembic.ini"
    if not ini.exists():
        ini = Path.cwd() / "alembic.ini"
    if not ini.exists():
        return
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _engine_for_path(db_path: Path):
    from aecc.db import create_engine_for_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_migrated(db_path)
    return create_engine_for_path(db_path)


def create_app(engine=None) -> FastAPI:
    """Application factory. Pass an engine for tests; otherwise file-backed."""
    app = FastAPI(title="AECC Operator Dashboard V1")

    if engine is None:
        engine = _engine_for_path(_default_db_path())

    from aecc.db import create_session_factory

    session_factory = create_session_factory(engine)

    def get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals.update(
        format_cost=vm.format_cost,
        format_cost_title=vm.format_cost_title,
        format_tokens=vm.format_tokens,
        format_elapsed=vm.format_elapsed,
        format_dt=vm.format_dt,
        verdict_label=vm.verdict_label,
        badge_class=vm.badge_class,
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/operator", response_class=HTMLResponse)
    def operator_overview(request: Request, session: Session = Depends(get_session)):
        rows = queries.fetch_runs_overview(session, limit=100)
        summary = queries.fetch_summary(session)
        return templates.TemplateResponse(
            request,
            "overview.html",
            {"rows": rows, "summary": summary, "active": "overview"},
        )

    @app.get("/operator/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: int, request: Request, session: Session = Depends(get_session)):
        detail = queries.fetch_run_detail(session, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        return templates.TemplateResponse(
            request, "run_detail.html", {"detail": detail, "active": "runs"}
        )

    @app.get("/operator/qualifications", response_class=HTMLResponse)
    def qualifications(request: Request, session: Session = Depends(get_session)):
        triples = queries.fetch_qualifications(session)
        return templates.TemplateResponse(
            request,
            "qualifications.html",
            {"triples": triples, "active": "qualifications"},
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # Expose session factory for tests/demo tooling.
    app.state.session_factory = session_factory
    app.state.engine = engine
    return app


# Default application instance (e.g. ``uvicorn aecc.web:app``).
try:
    app = create_app()
except Exception:
    # Import must never fail merely because no database file exists yet in a
    # fresh checkout; routes are still constructible via create_app(engine).
    app = None  # type: ignore[assignment]
