"""Operator Dashboard V1: FastAPI application entry point.

Server-rendered HTML (Jinja2) over the Phase 2 SQLite/SQLAlchemy evidence
foundation. Routes:

- GET /operator — overview with summary cards + recent runs table
- GET /operator/runs/{run_id} — evidence-oriented run detail (404 when missing)
- GET /operator/qualifications — one row per harness+model+capability triple
- GET /operator/capabilities — capability catalog (list)
- GET /operator/capabilities/new — add capability form
- POST /operator/capabilities — create capability
- GET /operator/capabilities/{id} — capability detail
- GET /operator/capabilities/{id}/edit — edit capability form
- POST /operator/capabilities/{id}/edit — update capability
- GET /operator/models — model registry (list)
- GET /operator/models/new — add model form
- POST /operator/models — create model
- GET /operator/models/{id} — model detail
- GET /operator/models/{id}/edit — edit model form
- POST /operator/models/{id}/edit — update model

The app queries persisted evidence per request; no hard-coded rows.
``create_app(engine=...)`` accepts an explicit engine so tests can bind an
isolated migrated SQLite database. Without an argument the app resolves the
database from ``AECC_DB_PATH`` (default ``data/evaluations.sqlite``) and
runs pending Alembic migrations.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from aecc import dashboard_queries as queries
from aecc import dashboard_viewmodels as vm
from aecc.models import Capability, Model

CAPABILITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
PRICING_TIERS = {"free", "paid", "unknown"}

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


def _parse_form_body(body: bytes) -> dict:
    """Parse x-www-form-urlencoded without requiring python-multipart."""
    if not body:
        return {}
    decoded = body.decode("utf-8", errors="ignore")
    parsed = urllib.parse.parse_qs(decoded, keep_blank_values=True)
    # flatten single values, keep list for multi?
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _capability_ancestors(session: Session, cap: Capability) -> list[Capability]:
    """Return ancestor chain from root to parent."""
    chain: list[Capability] = []
    cur = cap
    seen = set()
    while cur and cur.parent_id:
        if cur.parent_id in seen:
            break
        parent = session.get(Capability, cur.parent_id)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        cur = parent
        if len(chain) > 20:
            break
    chain.reverse()
    return chain


def _capability_children(session: Session, cap_id: int) -> list[Capability]:
    return list(
        session.scalars(
            select(Capability).where(Capability.parent_id == cap_id).order_by(Capability.capability_key)
        ).all()
    )


def _validate_capability_key(key: str) -> str | None:
    key = key.strip()
    if not key:
        return "Capability key is required."
    if len(key) > 255:
        return "Capability key too long (max 255)."
    if not CAPABILITY_KEY_RE.match(key):
        return "Capability key must be lowercase dot-separated (e.g. backend.fastapi.api_implementation)."
    return None


def _validate_model_fields(data: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not data.get("model_key", "").strip():
        errors["model_key"] = "Model key is required."
    if not data.get("provider", "").strip():
        errors["provider"] = "Provider is required."
    if not data.get("exact_identifier", "").strip():
        errors["exact_identifier"] = "Exact model identifier is required."
    tier = (data.get("pricing_tier") or "unknown").strip().lower()
    if tier not in PRICING_TIERS:
        errors["pricing_tier"] = "Pricing tier must be free, paid, or unknown."
    for field in ("price_input", "price_output"):
        val = data.get(field, "").strip()
        if val:
            try:
                f = float(val)
                if f < 0:
                    errors[field] = "Price must be non-negative."
            except ValueError:
                errors[field] = "Price must be numeric."
    return errors


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

    # ---- Capability Catalog ----
    @app.get("/operator/capabilities", response_class=HTMLResponse)
    def capabilities_list(request: Request, session: Session = Depends(get_session)):
        caps = list(
            session.scalars(select(Capability).order_by(Capability.capability_key, Capability.version)).all()
        )
        # build parent map for display
        parents = {}
        for c in caps:
            if c.parent_id:
                parents[c.id] = session.get(Capability, c.parent_id)
        return templates.TemplateResponse(
            request,
            "capabilities_list.html",
            {"capabilities": caps, "parents": parents, "active": "capabilities"},
        )

    @app.get("/operator/capabilities/new", response_class=HTMLResponse)
    def capability_new_form(request: Request, session: Session = Depends(get_session)):
        caps = list(session.scalars(select(Capability).order_by(Capability.capability_key)).all())
        return templates.TemplateResponse(
            request,
            "capability_form.html",
            {"mode": "new", "capability": None, "capabilities": caps, "errors": {}, "form": {}, "active": "capabilities"},
        )

    @app.post("/operator/capabilities", response_class=HTMLResponse)
    async def capability_create(request: Request, session: Session = Depends(get_session)):
        body = await request.body()
        form = _parse_form_body(body)
        errors: dict[str, str] = {}
        key = (form.get("capability_key") or "").strip()
        version = (form.get("version") or "").strip()
        display_name = (form.get("display_name") or "").strip() or None
        definition = (form.get("definition") or "").strip() or None
        description = (form.get("description") or "").strip() or None
        is_active = form.get("is_active") == "on" or form.get("is_active") == "true" or form.get("is_active") == "1"
        # default to active when not provided (checkbox unchecked means inactive)
        # If form has no is_active field at all, treat as True for new? Actually checkbox unchecked won't send field -> inactive
        # For UX, we treat missing as inactive if form submitted via our template with checkbox; else default active
        if "is_active" not in form:
            is_active = True
        parent_raw = (form.get("parent_id") or "").strip()
        parent_id = None
        if parent_raw:
            try:
                parent_id = int(parent_raw)
                if session.get(Capability, parent_id) is None:
                    errors["parent_id"] = "Parent capability not found."
            except ValueError:
                errors["parent_id"] = "Invalid parent."
        err = _validate_capability_key(key)
        if err:
            errors["capability_key"] = err
        if not version:
            errors["version"] = "Version is required."
        if errors:
            caps = list(session.scalars(select(Capability).order_by(Capability.capability_key)).all())
            return templates.TemplateResponse(
                request,
                "capability_form.html",
                {"mode": "new", "capability": None, "capabilities": caps, "errors": errors, "form": form, "active": "capabilities"},
                status_code=400,
            )
        # uniqueness check
        existing = session.scalar(
            select(Capability).where(Capability.capability_key == key, Capability.version == version)
        )
        if existing:
            errors["version"] = "A capability with this key and version already exists."
            caps = list(session.scalars(select(Capability).order_by(Capability.capability_key)).all())
            return templates.TemplateResponse(
                request,
                "capability_form.html",
                {"mode": "new", "capability": None, "capabilities": caps, "errors": errors, "form": form, "active": "capabilities"},
                status_code=400,
            )
        cap = Capability(
            capability_key=key,
            version=version,
            parent_id=parent_id,
            display_name=display_name,
            definition=definition,
            description=description,
            is_active=is_active,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(cap)
        session.commit()
        return RedirectResponse(url=f"/operator/capabilities/{cap.id}", status_code=303)

    @app.get("/operator/capabilities/{cap_id}", response_class=HTMLResponse)
    def capability_detail(cap_id: int, request: Request, session: Session = Depends(get_session)):
        cap = session.get(Capability, cap_id)
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        parent = session.get(Capability, cap.parent_id) if cap.parent_id else None
        children = _capability_children(session, cap.id)
        ancestors = _capability_ancestors(session, cap)
        # qualification history for this capability
        from aecc.models import QualificationDecision

        quals = list(
            session.scalars(
                select(QualificationDecision)
                .where(QualificationDecision.capability_id == cap.id)
                .order_by(QualificationDecision.id.desc())
            ).all()
        )
        return templates.TemplateResponse(
            request,
            "capability_detail.html",
            {
                "capability": cap,
                "parent": parent,
                "children": children,
                "ancestors": ancestors,
                "qualifications": quals,
                "active": "capabilities",
            },
        )

    @app.get("/operator/capabilities/{cap_id}/edit", response_class=HTMLResponse)
    def capability_edit_form(cap_id: int, request: Request, session: Session = Depends(get_session)):
        cap = session.get(Capability, cap_id)
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        caps = list(
            session.scalars(
                select(Capability).where(Capability.id != cap_id).order_by(Capability.capability_key)
            ).all()
        )
        form = {
            "capability_key": cap.capability_key,
            "version": cap.version,
            "display_name": cap.display_name or "",
            "definition": cap.definition or "",
            "description": cap.description or "",
            "parent_id": str(cap.parent_id) if cap.parent_id else "",
            "is_active": "on" if cap.is_active else "",
        }
        return templates.TemplateResponse(
            request,
            "capability_form.html",
            {"mode": "edit", "capability": cap, "capabilities": caps, "errors": {}, "form": form, "active": "capabilities"},
        )

    @app.post("/operator/capabilities/{cap_id}/edit", response_class=HTMLResponse)
    async def capability_update(cap_id: int, request: Request, session: Session = Depends(get_session)):
        cap = session.get(Capability, cap_id)
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        body = await request.body()
        form = _parse_form_body(body)
        errors: dict[str, str] = {}
        key = (form.get("capability_key") or "").strip()
        version = (form.get("version") or "").strip()
        display_name = (form.get("display_name") or "").strip() or None
        definition = (form.get("definition") or "").strip() or None
        description = (form.get("description") or "").strip() or None
        # checkbox handling: if missing -> inactive
        is_active = form.get("is_active") == "on" or form.get("is_active") == "true" or form.get("is_active") == "1"
        if "is_active" not in form:
            is_active = False
        parent_raw = (form.get("parent_id") or "").strip()
        parent_id = None
        if parent_raw:
            try:
                parent_id = int(parent_raw)
                if parent_id == cap.id:
                    errors["parent_id"] = "Capability cannot be its own parent."
                elif session.get(Capability, parent_id) is None:
                    errors["parent_id"] = "Parent capability not found."
                else:
                    # prevent cycle: ensure parent is not descendant
                    # walk up from parent
                    cur_id = parent_id
                    seen = set()
                    while cur_id:
                        if cur_id == cap.id:
                            errors["parent_id"] = "Cannot create cycle in hierarchy."
                            break
                        if cur_id in seen:
                            break
                        seen.add(cur_id)
                        cur = session.get(Capability, cur_id)
                        cur_id = cur.parent_id if cur else None
            except ValueError:
                errors["parent_id"] = "Invalid parent."
        err = _validate_capability_key(key)
        if err:
            errors["capability_key"] = err
        if not version:
            errors["version"] = "Version is required."
        # uniqueness if key/version changed
        if not errors and (key != cap.capability_key or version != cap.version):
            existing = session.scalar(
                select(Capability).where(Capability.capability_key == key, Capability.version == version)
            )
            if existing and existing.id != cap.id:
                errors["version"] = "A capability with this key and version already exists."
        if errors:
            caps = list(
                session.scalars(
                    select(Capability).where(Capability.id != cap_id).order_by(Capability.capability_key)
                ).all()
            )
            return templates.TemplateResponse(
                request,
                "capability_form.html",
                {"mode": "edit", "capability": cap, "capabilities": caps, "errors": errors, "form": form, "active": "capabilities"},
                status_code=400,
            )
        cap.capability_key = key
        cap.version = version
        cap.display_name = display_name
        cap.definition = definition
        cap.description = description
        cap.is_active = is_active
        cap.parent_id = parent_id
        cap.updated_at = datetime.now(timezone.utc)
        session.commit()
        return RedirectResponse(url=f"/operator/capabilities/{cap.id}", status_code=303)

    # ---- Model Registry ----
    @app.get("/operator/models", response_class=HTMLResponse)
    def models_list(request: Request, session: Session = Depends(get_session)):
        models = list(session.scalars(select(Model).order_by(Model.provider, Model.model_key)).all())
        return templates.TemplateResponse(
            request, "models_list.html", {"models": models, "active": "models"}
        )

    @app.get("/operator/models/new", response_class=HTMLResponse)
    def model_new_form(request: Request):
        return templates.TemplateResponse(
            request,
            "model_form.html",
            {"mode": "new", "model": None, "errors": {}, "form": {}, "active": "models"},
        )

    @app.post("/operator/models", response_class=HTMLResponse)
    async def model_create(request: Request, session: Session = Depends(get_session)):
        body = await request.body()
        form = _parse_form_body(body)
        errors = _validate_model_fields(form)
        model_key = (form.get("model_key") or "").strip()
        provider = (form.get("provider") or "").strip()
        exact_identifier = (form.get("exact_identifier") or "").strip()
        display_name = (form.get("display_name") or "").strip() or None
        pricing_tier = (form.get("pricing_tier") or "unknown").strip().lower()
        price_input_raw = (form.get("price_input") or "").strip()
        price_output_raw = (form.get("price_output") or "").strip()
        harness_config = (form.get("harness_config") or "").strip() or None
        description = (form.get("description") or "").strip() or None
        is_active = form.get("is_active") == "on" or form.get("is_active") == "true" or form.get("is_active") == "1"
        if "is_active" not in form:
            is_active = True
        # model_key uniqueness
        if model_key and session.scalar(select(Model).where(Model.model_key == model_key)):
            errors["model_key"] = "Model key already exists."
        if errors:
            return templates.TemplateResponse(
                request,
                "model_form.html",
                {"mode": "new", "model": None, "errors": errors, "form": form, "active": "models"},
                status_code=400,
            )
        price_input = float(price_input_raw) if price_input_raw else None
        price_output = float(price_output_raw) if price_output_raw else None
        m = Model(
            model_key=model_key,
            provider=provider,
            exact_identifier=exact_identifier,
            display_name=display_name,
            pricing_class=pricing_tier,
            pricing_tier=pricing_tier,
            price_input=price_input,
            price_output=price_output,
            is_active=is_active,
            harness_config=harness_config,
            description=description,
            updated_at=datetime.now(timezone.utc),
            config_params=harness_config,
        )
        session.add(m)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            errors["model_key"] = str(e)
            return templates.TemplateResponse(
                request,
                "model_form.html",
                {"mode": "new", "model": None, "errors": errors, "form": form, "active": "models"},
                status_code=400,
            )
        return RedirectResponse(url=f"/operator/models/{m.id}", status_code=303)

    @app.get("/operator/models/{model_id}", response_class=HTMLResponse)
    def model_detail(model_id: int, request: Request, session: Session = Depends(get_session)):
        m = session.get(Model, model_id)
        if m is None:
            raise HTTPException(status_code=404, detail="model not found")
        from aecc.models import QualificationDecision

        quals = list(
            session.scalars(
                select(QualificationDecision)
                .where(QualificationDecision.model_id == m.id)
                .order_by(QualificationDecision.id.desc())
            ).all()
        )
        return templates.TemplateResponse(
            request,
            "model_detail.html",
            {"model": m, "qualifications": quals, "active": "models"},
        )

    @app.get("/operator/models/{model_id}/edit", response_class=HTMLResponse)
    def model_edit_form(model_id: int, request: Request, session: Session = Depends(get_session)):
        m = session.get(Model, model_id)
        if m is None:
            raise HTTPException(status_code=404, detail="model not found")
        form = {
            "model_key": m.model_key,
            "provider": m.provider,
            "exact_identifier": m.exact_identifier,
            "display_name": m.display_name or "",
            "pricing_tier": m.pricing_tier or "unknown",
            "price_input": str(m.price_input) if m.price_input is not None else "",
            "price_output": str(m.price_output) if m.price_output is not None else "",
            "harness_config": m.harness_config or m.config_params or "",
            "description": m.description or "",
            "is_active": "on" if m.is_active else "",
        }
        return templates.TemplateResponse(
            request,
            "model_form.html",
            {"mode": "edit", "model": m, "errors": {}, "form": form, "active": "models"},
        )

    @app.post("/operator/models/{model_id}/edit", response_class=HTMLResponse)
    async def model_update(model_id: int, request: Request, session: Session = Depends(get_session)):
        m = session.get(Model, model_id)
        if m is None:
            raise HTTPException(status_code=404, detail="model not found")
        body = await request.body()
        form = _parse_form_body(body)
        errors = _validate_model_fields(form)
        model_key = (form.get("model_key") or "").strip()
        # uniqueness if changed
        if model_key != m.model_key and session.scalar(select(Model).where(Model.model_key == model_key)):
            errors["model_key"] = "Model key already exists."
        if errors:
            return templates.TemplateResponse(
                request,
                "model_form.html",
                {"mode": "edit", "model": m, "errors": errors, "form": form, "active": "models"},
                status_code=400,
            )
        m.model_key = model_key
        m.provider = (form.get("provider") or "").strip()
        m.exact_identifier = (form.get("exact_identifier") or "").strip()
        m.display_name = (form.get("display_name") or "").strip() or None
        pricing_tier = (form.get("pricing_tier") or "unknown").strip().lower()
        m.pricing_tier = pricing_tier
        m.pricing_class = pricing_tier
        price_input_raw = (form.get("price_input") or "").strip()
        price_output_raw = (form.get("price_output") or "").strip()
        m.price_input = float(price_input_raw) if price_input_raw else None
        m.price_output = float(price_output_raw) if price_output_raw else None
        m.harness_config = (form.get("harness_config") or "").strip() or None
        m.config_params = m.harness_config
        m.description = (form.get("description") or "").strip() or None
        # checkbox: missing means inactive
        if "is_active" in form:
            m.is_active = form.get("is_active") == "on" or form.get("is_active") == "true" or form.get("is_active") == "1"
        else:
            m.is_active = False
        m.updated_at = datetime.now(timezone.utc)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            errors["model_key"] = str(e)
            return templates.TemplateResponse(
                request,
                "model_form.html",
                {"mode": "edit", "model": m, "errors": errors, "form": form, "active": "models"},
                status_code=400,
            )
        return RedirectResponse(url=f"/operator/models/{m.id}", status_code=303)

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
