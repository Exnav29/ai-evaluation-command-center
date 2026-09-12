"""V2 Phase 1 shell + Home tests: navigation, plain language, evidence safety.

Covers populated-data behavior (seeded evidence) and empty-state rendering,
plus UNKNOWN/missing/demo semantics in the new Home summaries.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


@pytest.fixture()
def client(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "v2.sqlite"
    command.upgrade(_alembic_config(db_file), "head")

    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas, create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data

    apply_sqlite_pragmas(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        ids = seed_dashboard_data(session)

    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    test_client = TestClient(app, follow_redirects=False)
    test_client.ids = ids  # type: ignore[attr-defined]
    test_client.engine = engine  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        engine.dispose()


@pytest.fixture()
def empty_client(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "v2empty.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas

    apply_sqlite_pragmas(engine)
    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    test_client = TestClient(app, follow_redirects=False)
    try:
        yield test_client
    finally:
        engine.dispose()


V2_NAV = ["/home", "/test-model", "/rankings", "/help-me-choose", "/models", "/test-library", "/advanced"]


def test_v2_nav_present_on_home(client):
    html = client.get("/home").text
    assert client.get("/home").status_code == 200
    for href in V2_NAV:
        assert f'href="{href}"' in html


def test_no_global_technical_subnav_on_v2_pages(client):
    # The old technical sub-navigation must not persist on every V2 page;
    # technical pages stay reachable through Advanced and contextual links.
    for path in ("/home", "/rankings", "/help-me-choose", "/models", "/test-library", "/advanced"):
        html = client.get(path).text
        assert client.get(path).status_code == 200
        assert "topbar-sub" not in html
        assert 'aria-label="Technical evidence"' not in html


def test_root_redirects_to_home(client):
    resp = client.get("/")
    assert resp.status_code in (303, 307)
    assert resp.headers["location"].endswith("/home")


def test_home_primary_promise_and_actions(client):
    html = client.get("/home").text
    assert "Test AI models on real work" in html
    assert "get help choosing" in html
    assert 'data-testid="cta-test-model"' in html
    assert 'data-testid="cta-help-choose"' in html
    for slug in ("backend", "frontend", "visual-design", "reasoning", "instruction"):
        assert f'data-testid="work-card-{slug}"' in html


def test_home_populated_seed_shows_unknown_not_winners(client):
    # Seed capabilities (bug-fixing/refactoring) intentionally do not map to
    # the five V2 work areas, so populated seed data must render
    # "We don" without naming any winner or zero-filling.
    html = client.get("/home").text
    assert "We don" in html
    assert "frontier-x" not in html
    assert "cheap-free" not in html
    # Unmapped technical runs are disclosed, not hidden or zeroed.
    assert "don&rsquo;t map" in html or "don't map" in html or "Technical Details" in html


def test_home_empty_state(empty_client):
    html = empty_client.get("/home").text
    assert empty_client.get("/home").status_code == 200
    assert "We don" in html
    assert "No test runs map" in html


def test_models_shell_exposes_add_new_model(client, empty_client):
    for c in (client, empty_client):
        html = c.get("/models").text
        assert c.get("/models").status_code == 200
        assert "Add New Model" in html
        assert 'data-testid="add-new-model"' in html
        assert "/operator/models/new" in html
    # Populated registry lists exact identifiers without deepening workflow.
    html = client.get("/models").text
    assert "test-provider/opencode-cheap-1.0-extended-identifier-for-readability" in html


def test_rankings_no_composite_or_winners(client):
    html = client.get("/rankings").text
    assert client.get("/rankings").status_code == 200
    assert "Who" in html  # Who's Ready plain language
    assert "We don" in html
    # No ordered leaderboard or invented winner from seed data.
    assert "frontier-x" not in html


def test_help_me_choose_shell(client):
    html = client.get("/help-me-choose").text
    assert client.get("/help-me-choose").status_code == 200
    assert "Help Me Choose" in html
    assert "We don" in html
    assert "Good, but check its work" in html
    assert "Not a good choice for this work" in html


def test_test_library_and_advanced(client):
    lib = client.get("/test-library").text
    assert "Test Library" in lib
    assert "dashboard-login-fix" in lib
    adv = client.get("/advanced").text
    assert "Technical Details" in adv
    for href in ("/operator", "/operator/compare", "/operator/qualification", "/operator/tests",
                 "/operator/capabilities", "/operator/models", "/operator/qualifications"):
        assert f'href="{href}"' in adv
    # Plain-language glossary present.
    assert "Work Setup" in adv and "Harness" in adv


def test_legacy_operator_routes_still_work(client):
    ids = client.ids
    assert client.get("/operator").status_code == 200
    assert client.get(f"/operator/runs/{ids['runs']['r1']}").status_code == 200
    assert client.get("/operator/compare").status_code == 200
    assert client.get("/operator/qualification").status_code == 200
    assert client.get("/operator/qualifications").status_code == 200
    assert client.get("/operator/tests").status_code == 200
    assert client.get("/operator/models").status_code == 200
    assert client.get("/operator/capabilities").status_code == 200


def test_work_area_mapping_is_conservative():
    from aecc.work_areas import map_capability_to_work_area as m

    assert m("backend.api.v1") == "backend"
    assert m("frontend.render.v2") == "frontend"
    assert m("visual.design.v1") == "visual-design"
    assert m("reasoning.planning.v1") == "reasoning"
    assert m("instruction.following.v1") == "instruction"
    # Legacy/unknown keys never map (no invented coverage).
    assert m("bug-fixing") is None
    assert m("refactoring") is None
    assert m("") is None
    assert m(None) is None


def test_home_summary_with_mapped_evidence(tmp_path):
    """Mapped backend capability with PASS evidence shows counts, no winner rank."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "v2mapped.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas, create_session_factory

    apply_sqlite_pragmas(engine)
    factory = create_session_factory(engine)
    from datetime import datetime, timezone

    from aecc.models import (
        Attempt,
        Capability,
        EvaluatorVerdict,
        Harness,
        LogicalTest,
        Model,
        ProcessOutcome,
        DeliverableOutcome,
        TaskOutcome,
        RepoModificationOutcome,
        Run,
        RunState,
        ScoreRevision,
        TestVersion,
    )

    with factory() as s:
        cap = Capability(capability_key="backend.api", version="v1", is_active=True)
        h = Harness(harness_key="opencode")
        m1 = Model(model_key="m1", provider="p", exact_identifier="p/m1")
        lt = LogicalTest(key="t1", name="T1")
        s.add_all([cap, h, m1, lt])
        s.flush()
        tv = TestVersion(
            logical_test_id=lt.id, version_number=1, task_prompt="do",
            capability_key="backend.api", acceptance_criteria="ac",
            rubric_id="r", rubric_version="1", permission_profile="P",
            definition_hash="h",
        )
        s.add(tv)
        s.flush()
        now = datetime.now(timezone.utc)
        r = Run(test_version_id=tv.id, harness_id=h.id, model_id=m1.id,
                capability_id=cap.id, state=RunState.FINALIZED, requested_at=now)
        s.add(r)
        s.flush()
        a = Attempt(run_id=r.id, attempt_number=1, process_outcome=ProcessOutcome.SUCCESS,
                    deliverable_outcome=DeliverableOutcome.PRESENT, task_outcome=TaskOutcome.SUCCEEDED,
                    repo_modification_outcome=RepoModificationOutcome.MODIFIED, sealed_at=now)
        s.add(a)
        s.flush()
        s.add(ScoreRevision(run_id=r.id, attempt_id=a.id, rubric_version="r/1", verdict=EvaluatorVerdict.PASS))
        s.commit()
    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    c = TestClient(app)
    html = c.get("/home").text
    assert 'data-testid="work-card-backend"' in html
    backend = html.split('data-testid="work-card-backend"')[1].split("</article>")[0]
    assert "We don" not in backend
    assert "passing result" in backend
    # Other areas remain unknown; no winner named on Home.
    frontend = html.split('data-testid="work-card-frontend"')[1].split("</article>")[0]
    assert "We don" in frontend
    engine.dispose()


def test_home_unknown_and_demo_excluded(tmp_path):
    """UNKNOWN verdicts and demo runs never create passing evidence."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "v2demo.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas, create_session_factory

    apply_sqlite_pragmas(engine)
    factory = create_session_factory(engine)
    from datetime import datetime, timezone

    from aecc.models import (
        Attempt, Capability, EvaluatorVerdict, Harness, LogicalTest, Model,
        Run, RunState, ScoreRevision, TestVersion,
    )

    with factory() as s:
        cap = Capability(capability_key="backend.api", version="v1", is_active=True)
        h = Harness(harness_key="opencode")
        m1 = Model(model_key="m1", provider="p", exact_identifier="p/m1")
        lt = LogicalTest(key="t1", name="T1")
        s.add_all([cap, h, m1, lt])
        s.flush()
        tv = TestVersion(
            logical_test_id=lt.id, version_number=1, task_prompt="do",
            capability_key="backend.api", acceptance_criteria="ac",
            rubric_id="r", rubric_version="1", permission_profile="P",
            definition_hash="h",
        )
        s.add(tv)
        s.flush()
        now = datetime.now(timezone.utc)
        # UNKNOWN scored run (real, completed)
        r1 = Run(test_version_id=tv.id, harness_id=h.id, model_id=m1.id,
                 capability_id=cap.id, state=RunState.FINALIZED, requested_at=now)
        s.add(r1)
        s.flush()
        a1 = Attempt(run_id=r1.id, attempt_number=1, sealed_at=now)
        s.add(a1)
        s.flush()
        s.add(ScoreRevision(run_id=r1.id, attempt_id=a1.id, rubric_version="r/1",
                            verdict=EvaluatorVerdict.UNKNOWN))
        # Demo PASS run must not count toward real summaries.
        r2 = Run(test_version_id=tv.id, harness_id=h.id, model_id=m1.id,
                 capability_id=cap.id, state=RunState.FINALIZED, requested_at=now, is_demo=True)
        s.add(r2)
        s.flush()
        a2 = Attempt(run_id=r2.id, attempt_number=1, sealed_at=now, is_demo=True)
        s.add(a2)
        s.flush()
        s.add(ScoreRevision(run_id=r2.id, attempt_id=a2.id, rubric_version="r/1",
                            verdict=EvaluatorVerdict.PASS, is_demo=True))
        s.commit()
    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    c = TestClient(app)
    html = c.get("/home").text
    backend = html.split('data-testid="work-card-backend"')[1].split("</article>")[0]
    assert "We don" in backend
    engine.dispose()
