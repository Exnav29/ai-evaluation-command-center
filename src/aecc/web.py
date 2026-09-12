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
- GET /operator/tests — test registry list
- GET /operator/tests/new — new logical test form
- POST /operator/tests — create logical test
- GET /operator/tests/{id} — logical test detail with versions
- GET /operator/tests/{id}/versions/new — register new version form
- POST /operator/tests/{id}/versions — register new version
- GET /operator/tests/versions/{version_id} — version detail

The app queries persisted evidence per request; no hard-coded rows.
``create_app(engine=...)`` accepts an explicit engine so tests can bind an
isolated migrated SQLite database. Without an argument the app resolves the
database from ``AECC_DB_PATH`` (default ``data/evaluations.sqlite``) and
runs pending Alembic migrations.
"""

from __future__ import annotations

import json
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
from aecc.models import Capability, Harness, LogicalTest, Model, Run, TestVersion

CAPABILITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
LOGICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_\-\.]*$")
PRICING_TIERS = {"free", "paid", "unknown"}

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _get_repo_root() -> Path:
    """Return the AECC repository root (``src/aecc`` -> parents[1])."""
    return HERE.parents[1] if len(HERE.parents) >= 2 else Path.cwd()


def _default_db_path() -> Path:
    override = os.environ.get("AECC_DB_PATH")
    if override:
        return Path(override)
    root = _get_repo_root()
    candidate = root / "data" / "evaluations.sqlite"
    if candidate.parent.exists() or root.name != "/":
        return candidate
    return Path.cwd() / "data" / "evaluations.sqlite"


def _ensure_migrated(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    root = _get_repo_root()
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


def _validate_logical_test_fields(data: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    key = (data.get("key") or "").strip()
    name = (data.get("name") or "").strip()
    if not key:
        errors["key"] = "Logical test key is required."
    elif len(key) > 255:
        errors["key"] = "Key too long (max 255)."
    elif not LOGICAL_KEY_RE.match(key):
        errors["key"] = "Key must be lowercase alphanumeric, dot, dash or underscore, starting with a letter."
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 500:
        errors["name"] = "Name too long (max 500)."
    return errors


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


def _validate_version_fields(data: dict, active_cap_ids: set[str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    cap_val = (data.get("capability_id") or data.get("capability_key") or "").strip()
    if not cap_val:
        errors["capability_id"] = "Capability is required."
    elif cap_val not in active_cap_ids:
        errors["capability_id"] = "Selected capability is not active or not found."
    if not (data.get("task_prompt") or "").strip():
        errors["task_prompt"] = "Task prompt is required."
    if not (data.get("acceptance_criteria") or "").strip():
        errors["acceptance_criteria"] = "Acceptance criteria is required."
    if not (data.get("rubric_id") or "").strip():
        errors["rubric_id"] = "Rubric ID is required."
    if not (data.get("rubric_version") or "").strip():
        errors["rubric_version"] = "Rubric version is required."
    if not (data.get("permission_profile") or "").strip():
        errors["permission_profile"] = "Permission profile is required."
    timeout_raw = (data.get("timeout_seconds") or "").strip()
    if timeout_raw:
        try:
            iv = int(timeout_raw)
            if iv < 0:
                errors["timeout_seconds"] = "Timeout must be non-negative."
            if iv > 86400 * 7:
                errors["timeout_seconds"] = "Timeout too large."
        except ValueError:
            errors["timeout_seconds"] = "Timeout must be an integer (seconds)."
    # retry_policy JSON
    retry_raw = (data.get("retry_policy") or "").strip()
    if retry_raw:
        try:
            json.loads(retry_raw)
        except Exception:
            errors["retry_policy"] = "Retry policy must be valid JSON."
    expected_raw = (data.get("expected_artifacts") or "").strip()
    if expected_raw:
        try:
            json.loads(expected_raw)
        except Exception:
            errors["expected_artifacts"] = "Expected artifacts must be valid JSON."
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

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/operator", status_code=307)

    @app.get("/operator", response_class=HTMLResponse)
    def operator_overview(request: Request, session: Session = Depends(get_session)):
        rows = queries.fetch_runs_overview(session, limit=100)
        summary = queries.fetch_summary(session)
        from aecc import chart_queries as charts

        chart_payload = charts.fetch_overview_charts(session)
        # demo banner
        from aecc.demo import has_demo_data
        has_demo = has_demo_data(session)
        demo_counts = None
        if has_demo:
            from sqlalchemy import func as _func
            demo_counts = int(session.scalar(select(_func.count(Run.id)).where(Run.is_demo == True)) or 0)  # noqa: E712
        return templates.TemplateResponse(
            request,
            "overview.html",
            {"rows": rows, "summary": summary, "active": "overview", "has_demo": has_demo, "demo_counts": demo_counts, "charts": chart_payload},
        )

    @app.get("/operator/runs/new", response_class=HTMLResponse)
    def run_new_form(request: Request, session: Session = Depends(get_session)):
        import uuid

        versions = list(session.scalars(select(TestVersion).order_by(TestVersion.logical_test_id, TestVersion.version_number)).all())
        logical_map = {}
        if versions:
            lts = session.scalars(select(LogicalTest).where(LogicalTest.id.in_({v.logical_test_id for v in versions}))).all()
            logical_map = {lt.id: lt for lt in lts}
        models = list(session.scalars(select(Model).where(Model.is_active == True).order_by(Model.provider, Model.model_key)).all())  # noqa: E712
        harnesses = list(session.scalars(select(Harness).order_by(Harness.harness_key)).all())
        # idempotency token
        token = str(uuid.uuid4())
        return templates.TemplateResponse(
            request,
            "run_form.html",
            {"versions": versions, "logical_map": logical_map, "models": models, "harnesses": harnesses, "token": token, "errors": {}, "active": "overview"},
        )

    @app.post("/operator/runs", response_class=HTMLResponse)
    async def run_create(request: Request, session: Session = Depends(get_session)):
        import uuid

        body = await request.body()
        form = _parse_form_body(body)
        test_version_id_raw = (form.get("test_version_id") or "").strip()
        model_id_raw = (form.get("model_id") or "").strip()
        harness_id_raw = (form.get("harness_id") or "").strip()
        idempotency_key = (form.get("idempotency_key") or "").strip() or str(uuid.uuid4())
        errors: dict[str, str] = {}
        # Validate
        try:
            tv_id = int(test_version_id_raw)
            tv = session.get(TestVersion, tv_id)
            if tv is None:
                errors["test_version_id"] = "Selected test version not found."
        except ValueError:
            errors["test_version_id"] = "Invalid test version."
            tv = None
        try:
            m_id = int(model_id_raw)
            m = session.get(Model, m_id)
            if m is None or not m.is_active:
                errors["model_id"] = "Selected model not found or inactive."
        except ValueError:
            errors["model_id"] = "Invalid model."
            m = None
        harness_id = None
        if harness_id_raw:
            try:
                harness_id = int(harness_id_raw)
                if session.get(Harness, harness_id) is None:
                    errors["harness_id"] = "Harness not found."
            except ValueError:
                errors["harness_id"] = "Invalid harness."
        # Idempotency is decided by the service layer: same key + same parameters
        # returns the existing run; same key + different parameters is refused.
        if errors:
            versions = list(session.scalars(select(TestVersion).order_by(TestVersion.logical_test_id, TestVersion.version_number)).all())
            logical_map = {}
            if versions:
                lts = session.scalars(select(LogicalTest).where(LogicalTest.id.in_({v.logical_test_id for v in versions}))).all()
                logical_map = {lt.id: lt for lt in lts}
            models = list(session.scalars(select(Model).where(Model.is_active == True).order_by(Model.provider, Model.model_key)).all())  # noqa: E712
            harnesses = list(session.scalars(select(Harness).order_by(Harness.harness_key)).all())
            return templates.TemplateResponse(
                request,
                "run_form.html",
                {"versions": versions, "logical_map": logical_map, "models": models, "harnesses": harnesses, "token": idempotency_key, "errors": errors, "form": form, "active": "overview"},
                status_code=400,
            )
        # Delegate to the service layer off the event loop with its own
        # database session: harness execution can take up to the test
        # version's timeout and must not block the async request worker or
        # share the request-scoped session across threads.
        from aecc.execution import execute_run
        from starlette.concurrency import run_in_threadpool

        def _run_execution():
            work_session = session_factory()
            try:
                return execute_run(
                    work_session,
                    test_version_id=tv.id,  # type: ignore
                    model_id=m.id,  # type: ignore
                    harness_id=harness_id,
                    idempotency_key=idempotency_key,
                    requested_by="operator",
                    is_demo=False,
                )
            finally:
                work_session.close()

        try:
            run, attempt, result = await run_in_threadpool(_run_execution)
        except ValueError as e:
            errors["test_version_id"] = str(e)
            versions = list(session.scalars(select(TestVersion).order_by(TestVersion.logical_test_id, TestVersion.version_number)).all())
            logical_map = {}
            if versions:
                lts = session.scalars(select(LogicalTest).where(LogicalTest.id.in_({v.logical_test_id for v in versions}))).all()
                logical_map = {lt.id: lt for lt in lts}
            models = list(session.scalars(select(Model).where(Model.is_active == True).order_by(Model.provider, Model.model_key)).all())  # noqa: E712
            harnesses = list(session.scalars(select(Harness).order_by(Harness.harness_key)).all())
            return templates.TemplateResponse(
                request,
                "run_form.html",
                {"versions": versions, "logical_map": logical_map, "models": models, "harnesses": harnesses, "token": idempotency_key, "errors": errors, "form": form, "active": "overview"},
                status_code=400,
            )
        return RedirectResponse(url=f"/operator/runs/{run.id}", status_code=303)

    @app.post("/operator/demo/clear", response_class=HTMLResponse)
    async def demo_clear(request: Request, session: Session = Depends(get_session)):
        from aecc.demo import clear_demo_data, has_demo_data

        from aecc.demo import DemoDataReferencedError

        if not has_demo_data(session):
            return RedirectResponse(url="/operator", status_code=303)
        try:
            clear_demo_data(session)
        except DemoDataReferencedError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return RedirectResponse(url="/operator", status_code=303)

    @app.post("/operator/demo/seed", response_class=HTMLResponse)
    async def demo_seed(request: Request, session: Session = Depends(get_session)):
        from aecc.demo import has_demo_data, seed_demo_data

        # Only seed if no demo yet and requested explicitly; prevents accidental reseed
        if has_demo_data(session):
            return RedirectResponse(url="/operator", status_code=303)
        seed_demo_data(session)
        return RedirectResponse(url="/operator", status_code=303)

    @app.get("/operator/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: int, request: Request, session: Session = Depends(get_session)):
        detail = queries.fetch_run_detail(session, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        # Deterministic per-run evidence classification for the comparison /
        # qualification milestone (no extra queries; derived from the detail
        # bundle so drill-down stays consistent with compare/qualification).
        from aecc.qualification import RunEvidence, classify_run

        latest = detail.get("latest_score")
        latest_a = detail.get("latest_attempt")
        run = detail["run"]
        evidence_category = classify_run(
            RunEvidence(
                run_id=run.id,
                verdict=latest.verdict.value if latest is not None and latest.verdict is not None else None,
                run_state=run.state.value if run.state is not None else None,
                failure_primary=(
                    latest_a.failure_primary.value
                    if latest_a is not None and latest_a.failure_primary is not None
                    else None
                ),
                has_intervention=bool(detail.get("has_intervention")),
                has_permission_denial=bool(detail.get("has_permission_denial")),
                has_exclusion=bool(detail.get("exclusions")),
                is_demo=bool(run.is_demo),
            )
        ).category
        return templates.TemplateResponse(
            request, "run_detail.html", {"detail": detail, "evidence_category": evidence_category, "active": "runs"}
        )

    @app.get("/operator/qualifications", response_class=HTMLResponse)
    def qualifications(request: Request, session: Session = Depends(get_session)):
        triples = queries.fetch_qualifications(session)
        return templates.TemplateResponse(
            request,
            "qualifications.html",
            {"triples": triples, "active": "qualifications"},
        )

    @app.get("/operator/qualification", response_class=HTMLResponse)
    def computed_qualification(request: Request, session: Session = Depends(get_session)):
        """Deterministic computed qualification per triple with why-reasons.

        Reads completed evidence only; demo rows are excluded from real
        qualification and no LLM is involved.
        """
        triples = queries.fetch_computed_qualifications(session)
        from aecc import chart_queries as charts

        chart_payload = charts.fetch_overview_charts(session)
        return templates.TemplateResponse(
            request,
            "qualification.html",
            {"triples": triples, "active": "qualification", "charts": chart_payload},
        )

    @app.get("/operator/compare", response_class=HTMLResponse)
    def compare(request: Request, session: Session = Depends(get_session)):
        """Side-by-side comparison of completed evidence in one test context."""
        from aecc.qualification import assess_triple

        params = request.query_params
        capability_id = None
        test_version_id = None
        raw_cap = params.get("capability_id")
        raw_tv = params.get("test_version_id")
        if raw_cap:
            try:
                capability_id = int(raw_cap)
            except ValueError:
                raise HTTPException(status_code=400, detail="capability_id must be an integer")
            if session.get(Capability, capability_id) is None:
                raise HTTPException(status_code=404, detail="capability not found")
        if raw_tv:
            try:
                test_version_id = int(raw_tv)
            except ValueError:
                raise HTTPException(status_code=400, detail="test_version_id must be an integer")
            if session.get(TestVersion, test_version_id) is None:
                raise HTTPException(status_code=404, detail="test version not found")

        contexts = queries.fetch_compare_contexts(session)
        rows = queries.fetch_compare_rows(
            session, capability_id=capability_id, test_version_id=test_version_id
        )

        # Computed assessment per exact test context represented in this view,
        # derived deterministically from the displayed evidence (demo rows set
        # aside). Grouping preserves harness+model+capability+test_version so
        # different logical tests or materially different definitions never
        # silently blend into one qualification.
        by_group: dict[tuple[int, int, int, int], list[dict]] = {}
        for row in rows:
            run = row["run"]
            by_group.setdefault((run.harness_id, run.model_id, run.capability_id, run.test_version_id), []).append(row)
        assessments: list[dict] = []
        for group, group_rows in by_group.items():
            ordered = sorted(group_rows, key=lambda r: r["run"].id)
            assessment = assess_triple([r["evidence"] for r in ordered])
            first = ordered[0]
            assessments.append(
                {
                    "triple": group[:3],
                    "group": group,
                    "harness": first["harness"],
                    "model": first["model"],
                    "capability": first["capability"],
                    "test_version": first["test_version"],
                    "logical_test": first["logical_test"],
                    "assessment": assessment,
                }
            )

        def _sort_key(a: dict) -> tuple:
            h, m, c = a["harness"], a["model"], a["capability"]
            tv = a.get("test_version")
            lt = a.get("logical_test")
            return (
                h.harness_key if h is not None else "",
                m.model_key if m is not None else "",
                c.capability_key if c is not None else "",
                c.version if c is not None and c.version else "",
                lt.key if lt is not None else "",
                tv.version_number if tv is not None else 0,
            )

        assessments.sort(key=_sort_key)
        from aecc import chart_queries as charts

        chart_payload = charts.fetch_context_charts(
            session,
            capability_id=capability_id,
            test_version_id=test_version_id,
        )
        return templates.TemplateResponse(
            request,
            "compare.html",
            {
                "rows": rows,
                "assessments": assessments,
                "contexts": contexts,
                "selected_capability_id": capability_id,
                "selected_test_version_id": test_version_id,
                "active": "compare",
                "charts": chart_payload,
            },
        )

    # ---- Capability Catalog ----
    @app.get("/operator/capabilities", response_class=HTMLResponse)
    def capabilities_list(request: Request, session: Session = Depends(get_session)):
        caps = list(
            session.scalars(select(Capability).order_by(Capability.capability_key, Capability.version)).all()
        )
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

    # ---- Test Registry ----
    @app.get("/operator/tests", response_class=HTMLResponse)
    def tests_list(request: Request, session: Session = Depends(get_session)):
        tests = list(session.scalars(select(LogicalTest).order_by(LogicalTest.key)).all())
        # map logical_test_id -> versions
        versions_by_test: dict[int, list[TestVersion]] = {}
        if tests:
            all_versions = list(session.scalars(select(TestVersion).order_by(TestVersion.logical_test_id, TestVersion.version_number)).all())
            for v in all_versions:
                versions_by_test.setdefault(v.logical_test_id, []).append(v)
        # latest per test
        latest_by_test: dict[int, TestVersion | None] = {}
        for t in tests:
            vs = versions_by_test.get(t.id, [])
            latest_by_test[t.id] = max(vs, key=lambda x: x.version_number) if vs else None
        return templates.TemplateResponse(
            request,
            "tests_list.html",
            {"tests": tests, "versions_by_test": versions_by_test, "latest_by_test": latest_by_test, "active": "tests"},
        )

    @app.get("/operator/tests/new", response_class=HTMLResponse)
    def test_new_form(request: Request):
        return templates.TemplateResponse(
            request,
            "test_form.html",
            {"errors": {}, "form": {}, "active": "tests"},
        )

    @app.post("/operator/tests", response_class=HTMLResponse)
    async def test_create(request: Request, session: Session = Depends(get_session)):
        body = await request.body()
        form = _parse_form_body(body)
        errors = _validate_logical_test_fields(form)
        key = (form.get("key") or "").strip()
        name = (form.get("name") or "").strip()
        description = (form.get("description") or "").strip() or None
        if key and session.scalar(select(LogicalTest).where(LogicalTest.key == key)):
            errors["key"] = "Logical test key already exists."
        if errors:
            return templates.TemplateResponse(
                request, "test_form.html", {"errors": errors, "form": form, "active": "tests"}, status_code=400
            )
        lt = LogicalTest(key=key, name=name, description=description, created_at=datetime.now(timezone.utc))
        session.add(lt)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            errors["key"] = str(e)
            return templates.TemplateResponse(
                request, "test_form.html", {"errors": errors, "form": form, "active": "tests"}, status_code=400
            )
        return RedirectResponse(url=f"/operator/tests/{lt.id}", status_code=303)

    @app.get("/operator/tests/{test_id}", response_class=HTMLResponse)
    def test_detail(test_id: int, request: Request, session: Session = Depends(get_session)):
        lt = session.get(LogicalTest, test_id)
        if lt is None:
            raise HTTPException(status_code=404, detail="logical test not found")
        versions = list(
            session.scalars(
                select(TestVersion).where(TestVersion.logical_test_id == test_id).order_by(TestVersion.version_number.asc())
            ).all()
        )
        latest = max(versions, key=lambda x: x.version_number) if versions else None
        # resolve exact capability objects for history display (preserve exact version)
        cap_map: dict[tuple[str, str | None], Capability] = {}
        # also simple key fallback for older rows without version
        cap_map_key: dict[str, Capability] = {}
        if versions:
            # collect exact pairs
            pairs = {(v.capability_key, v.capability_version) for v in versions if v.capability_version}
            keys_only = {v.capability_key for v in versions if not v.capability_version}
            caps_exact = []
            if pairs:
                # fetch exact matches
                for k, ver in pairs:
                    c = session.scalar(select(Capability).where(Capability.capability_key == k, Capability.version == ver))
                    if c:
                        cap_map[(k, ver)] = c
                        # also fill key fallback
                        if k not in cap_map_key or (c.is_active and not cap_map_key[k].is_active):
                            cap_map_key[k] = c
                    else:
                        # no exact match (maybe deleted) – try any version for that key
                        fallback = session.scalar(select(Capability).where(Capability.capability_key == k).order_by(Capability.is_active.desc(), Capability.version.desc()))
                        if fallback:
                            cap_map[(k, ver)] = fallback
            if keys_only:
                caps = list(session.scalars(select(Capability).where(Capability.capability_key.in_(sorted(keys_only)))).all())
                for c in caps:
                    existing = cap_map_key.get(c.capability_key)
                    if existing is None or (c.is_active and not existing.is_active):
                        cap_map_key[c.capability_key] = c
        return templates.TemplateResponse(
            request,
            "test_detail.html",
            {"logical_test": lt, "versions": versions, "latest": latest, "cap_map": cap_map, "cap_map_key": cap_map_key, "active": "tests"},
        )

    @app.get("/operator/tests/{test_id}/versions/new", response_class=HTMLResponse)
    def version_new_form(test_id: int, request: Request, session: Session = Depends(get_session)):
        lt = session.get(LogicalTest, test_id)
        if lt is None:
            raise HTTPException(status_code=404, detail="logical test not found")
        # only active capabilities offered
        active_caps = list(session.scalars(select(Capability).where(Capability.is_active == True).order_by(Capability.capability_key, Capability.version)).all())  # noqa: E712
        versions = list(
            session.scalars(select(TestVersion).where(TestVersion.logical_test_id == test_id).order_by(TestVersion.version_number.desc())).all()
        )
        latest = versions[0] if versions else None
        return templates.TemplateResponse(
            request,
            "version_form.html",
            {"logical_test": lt, "active_capabilities": active_caps, "latest": latest, "errors": {}, "form": {}, "active": "tests"},
        )

    @app.post("/operator/tests/{test_id}/versions", response_class=HTMLResponse)
    async def version_create(test_id: int, request: Request, session: Session = Depends(get_session)):
        lt = session.get(LogicalTest, test_id)
        if lt is None:
            raise HTTPException(status_code=404, detail="logical test not found")
        body = await request.body()
        form = _parse_form_body(body)
        active_caps = list(session.scalars(select(Capability).where(Capability.is_active == True).order_by(Capability.capability_key, Capability.version)).all())  # noqa: E712
        active_ids = {str(c.id) for c in active_caps}
        # backward-compat: allow capability_key fallback only if id not supplied, but prefer id
        errors = _validate_version_fields(form, active_ids)
        # if form used legacy capability_key, map to id for error messaging
        if errors and "capability_id" in errors and form.get("capability_key"):
            # try to provide clearer error
            pass
        if errors:
            versions = list(session.scalars(select(TestVersion).where(TestVersion.logical_test_id == test_id).order_by(TestVersion.version_number.desc())).all())
            latest = versions[0] if versions else None
            return templates.TemplateResponse(
                request,
                "version_form.html",
                {"logical_test": lt, "active_capabilities": active_caps, "latest": latest, "errors": errors, "form": form, "active": "tests"},
                status_code=400,
            )
        # gather fields – capability is selected as exact id/version pair
        capability_id_raw = (form.get("capability_id") or "").strip()
        capability_key = ""
        capability_version = None
        selected_cap = None
        if capability_id_raw:
            try:
                selected_cap = session.get(Capability, int(capability_id_raw))
            except ValueError:
                selected_cap = None
            if selected_cap and selected_cap.is_active:
                capability_key = selected_cap.capability_key
                capability_version = selected_cap.version
            else:
                # fallback: try treating raw as key for legacy path (should have been rejected)
                capability_key = (form.get("capability_key") or capability_id_raw).strip()
                # try to resolve version
                if selected_cap:
                    capability_version = selected_cap.version
                else:
                    # attempt to lookup active key
                    fallback = session.scalar(select(Capability).where(Capability.capability_key == capability_key, Capability.is_active == True))  # noqa: E712
                    if fallback:
                        capability_version = fallback.version
        else:
            # legacy fallback
            capability_key = (form.get("capability_key") or "").strip()
            fallback = session.scalar(select(Capability).where(Capability.capability_key == capability_key, Capability.is_active == True))  # noqa: E712
            if fallback:
                capability_version = fallback.version

        task_prompt = (form.get("task_prompt") or "").strip()
        acceptance_criteria = (form.get("acceptance_criteria") or "").strip()
        rubric_id = (form.get("rubric_id") or "").strip()
        rubric_version = (form.get("rubric_version") or "").strip()
        permission_profile = (form.get("permission_profile") or "").strip()
        source_fixture_ref = (form.get("source_fixture_ref") or "").strip() or None
        source_commit = (form.get("source_commit") or "").strip() or None
        harness_policy = (form.get("harness_policy") or "").strip() or None
        model_policy = (form.get("model_policy") or "").strip() or None
        retry_raw = (form.get("retry_policy") or "").strip() or None
        expected_raw = (form.get("expected_artifacts") or "").strip() or None
        timeout_raw = (form.get("timeout_seconds") or "").strip()
        timeout_seconds = int(timeout_raw) if timeout_raw else None
        description = (form.get("description") or "").strip() or None
        # if logical test has no description and version provides one, update logical description? keep separate
        # parse retry/expected for hashing
        retry_obj = None
        if retry_raw:
            try:
                retry_obj = json.loads(retry_raw)
            except Exception:
                retry_obj = retry_raw
        expected_obj = None
        if expected_raw:
            try:
                expected_obj = json.loads(expected_raw)
            except Exception:
                expected_obj = expected_raw

        # compute definition hash – includes exact capability version
        from aecc.hashing import build_definition_payload, canonical_definition_hash

        payload = build_definition_payload(
            task_prompt=task_prompt,
            acceptance_criteria=acceptance_criteria,
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            source_fixture_ref=source_fixture_ref,
            source_commit=source_commit,
            permission_profile=permission_profile,
            retry_policy=retry_obj,
            timeout_seconds=timeout_seconds,
            expected_artifacts=expected_obj,
            capability_key=capability_key,
            capability_version=capability_version,
        )
        definition_hash = canonical_definition_hash(payload)

        # determine next version number and supersedes
        existing = list(session.scalars(select(TestVersion).where(TestVersion.logical_test_id == test_id).order_by(TestVersion.version_number.desc())).all())
        next_number = (existing[0].version_number + 1) if existing else 1
        supersedes_id = existing[0].id if existing else None

        now = datetime.now(timezone.utc)
        tv = TestVersion(
            logical_test_id=test_id,
            version_number=next_number,
            task_prompt=task_prompt,
            capability_key=capability_key,
            capability_version=capability_version,
            acceptance_criteria=acceptance_criteria,
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            retry_policy=retry_raw,
            timeout_seconds=timeout_seconds,
            expected_artifacts=expected_raw,
            permission_profile=permission_profile,
            source_fixture_ref=source_fixture_ref,
            source_commit=source_commit,
            harness_policy=harness_policy,
            model_policy=model_policy,
            created_at=now,
            registered_at=now,
            definition_hash=definition_hash,
            supersedes_version_id=supersedes_id,
        )
        session.add(tv)
        # also update logical_test description if provided and logical has none
        if description and not lt.description:
            lt.description = description
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            errors["capability_id"] = str(e)
            versions = list(session.scalars(select(TestVersion).where(TestVersion.logical_test_id == test_id).order_by(TestVersion.version_number.desc())).all())
            latest = versions[0] if versions else None
            return templates.TemplateResponse(
                request,
                "version_form.html",
                {"logical_test": lt, "active_capabilities": active_caps, "latest": latest, "errors": errors, "form": form, "active": "tests"},
                status_code=400,
            )
        return RedirectResponse(url=f"/operator/tests/{test_id}", status_code=303)

    @app.get("/operator/tests/versions/{version_id}", response_class=HTMLResponse)
    def version_detail(version_id: int, request: Request, session: Session = Depends(get_session)):
        tv = session.get(TestVersion, version_id)
        if tv is None:
            raise HTTPException(status_code=404, detail="test version not found")
        lt = session.get(LogicalTest, tv.logical_test_id)
        # try to find exact capability object for preserved key+version, fallback to key
        cap = None
        if tv.capability_version:
            cap = session.scalar(select(Capability).where(Capability.capability_key == tv.capability_key, Capability.version == tv.capability_version))
        if cap is None:
            cap = session.scalar(select(Capability).where(Capability.capability_key == tv.capability_key).order_by(Capability.is_active.desc(), Capability.version.desc()))
        superseded = session.get(TestVersion, tv.supersedes_version_id) if tv.supersedes_version_id else None
        # find successor if any (who supersedes this)
        successor = session.scalar(select(TestVersion).where(TestVersion.supersedes_version_id == tv.id))
        # determine if latest
        latest = session.scalar(select(TestVersion).where(TestVersion.logical_test_id == tv.logical_test_id).order_by(TestVersion.version_number.desc()))
        is_latest = latest is not None and latest.id == tv.id
        return templates.TemplateResponse(
            request,
            "version_detail.html",
            {"version": tv, "logical_test": lt, "capability": cap, "superseded": superseded, "successor": successor, "is_latest": is_latest, "active": "tests"},
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
