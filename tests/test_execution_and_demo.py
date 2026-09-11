"""Execution Worker + Run Evaluation + Demo lifecycle tests."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from unittest import mock

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
# Captured at import time, before the autouse mock below replaces it.
from aecc.execution import _run_harness_process as _REAL_RUN_HARNESS_PROCESS  # noqa: E402

def _cfg(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg

def _make_client(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "exec.sqlite"
    command.upgrade(_cfg(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas
    apply_sqlite_pragmas(engine)
    from aecc.web import create_app
    from fastapi.testclient import TestClient
    app = create_app(engine=engine)
    client = TestClient(app, follow_redirects=False)
    client.engine = engine  # type: ignore
    return client, engine

@pytest.fixture()
def client(tmp_path):
    c, eng = _make_client(tmp_path)
    try:
        yield c
    finally:
        eng.dispose()

def _post(client, url, data, follow=False):
    body = urllib.parse.urlencode(data)
    return client.post(url, content=body, headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=follow)

def _setup_evidence(client):
    # create capability, harness, model, logical test + version
    # use web routes for consistency where possible, then ensure opencode runnable harness exists
    import json
    from aecc.models import Harness
    # capability
    _post(client, "/operator/capabilities", {"capability_key":"exec.cap","version":"v1","is_active":"on"}, follow=True)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Capability, Model, LogicalTest
        cap = s.scalar(select(Capability).where(Capability.capability_key=="exec.cap"))
        cap_id = cap.id
    # model
    _post(client, "/operator/models", {"model_key":"exec-model","provider":"test-prov","exact_identifier":"test-prov/exec-1","pricing_tier":"free","is_active":"on"}, follow=True)
    with factory() as s:
        from aecc.models import Model
        m = s.scalar(select(Model).where(Model.model_key=="exec-model"))
        mid = m.id
    # ensure runnable opencode harness exists (explicit adapter, not just version/build/mode)
    # Keep demo separation: user harness must not be the demo harness (which may be cleared)
    with factory() as s:
        demo_exists = s.scalar(select(Harness).where(Harness.is_demo == True).limit(1))
        if demo_exists is not None:
            # demo data present – ensure a distinct non-demo harness exists
            user_h = s.scalar(select(Harness).where(Harness.is_demo == False).order_by(Harness.id).limit(1))
            if user_h is None:
                # create non-demo harness with distinct key to avoid unique collision on "opencode"
                existing_keys = set(s.scalars(select(Harness.harness_key)).all())
                key = "opencode"
                if key in existing_keys:
                    key = "opencode-run"
                    if key in existing_keys:
                        key = "opencode-user"
                user_h = Harness(harness_key=key, display_name="opencode", config_snapshot=json.dumps({"adapter":"opencode"}), is_demo=False)
                s.add(user_h); s.flush()
            else:
                if not user_h.config_snapshot or "adapter" not in (user_h.config_snapshot or ""):
                    user_h.config_snapshot = json.dumps({"adapter":"opencode"})
            s.commit()
        else:
            h = s.scalar(select(Harness).where(Harness.harness_key=="opencode"))
            if h is None:
                h = Harness(harness_key="opencode", display_name="opencode", config_snapshot=json.dumps({"adapter":"opencode"}), is_demo=False)
                s.add(h); s.flush()
            else:
                h.config_snapshot = json.dumps({"adapter":"opencode"})
            s.commit()
    # logical test
    _post(client, "/operator/tests", {"key":"exec-test","name":"Exec Test"}, follow=True)
    with factory() as s:
        from aecc.models import LogicalTest
        lt = s.scalar(select(LogicalTest).where(LogicalTest.key=="exec-test"))
        lt_id = lt.id
    # version
    resp = _post(client, f"/operator/tests/{lt_id}/versions", {"capability_id":str(cap_id),"task_prompt":"do exec thing","acceptance_criteria":"must do","rubric_id":"r","rubric_version":"1","permission_profile":"READ_ONLY_NO_SHELL"}, follow=False)
    assert resp.status_code == 303
    with factory() as s:
        from aecc.models import TestVersion
        tv = s.scalar(select(TestVersion).where(TestVersion.logical_test_id==lt_id))
        tv_id = tv.id
    return {"cap_id":cap_id, "model_id":mid, "logical_id":lt_id, "tv_id":tv_id}


def _mock_success_run(*args, **kwargs):
    import subprocess
    return subprocess.CompletedProcess(args=args[0] if args else kwargs.get("args"), returncode=0, stdout="ok", stderr="")


def _mock_denied_run(*args, **kwargs):
    import subprocess
    return subprocess.CompletedProcess(args=args[0] if args else kwargs.get("args"), returncode=126, stdout="", stderr="denied: shell tool 'exec' not in profile")


@pytest.fixture(autouse=True)
def _auto_mock_opencode_success(monkeypatch):
    # Default mock: opencode binary available and the harness process returns
    # success (exit 0). Individual tests can override with their own mock for
    # denied/timeout cases. Infra/not-configured tests remain infra because
    # harness preflight fails regardless.
    monkeypatch.setattr("aecc.execution._is_opencode_available", lambda: True)
    monkeypatch.setattr("aecc.execution._run_harness_process", _mock_success_run)

def test_run_evaluation_form_loads(client):
    ids = _setup_evidence(client)
    resp = client.get("/operator/runs/new")
    assert resp.status_code == 200
    assert "Run Evaluation" in resp.text
    assert "Test version" in resp.text
    assert "Model" in resp.text
    assert "idempotency_key" in resp.text

def test_create_run_and_attempt_via_service(client):
    ids = _setup_evidence(client)
    # Get form to capture token
    html = client.get("/operator/runs/new").text
    import re
    m = re.search(r'name="idempotency_key" value="([^"]+)"', html)
    token = m.group(1) if m else "tok-123"
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":token}, follow=False)
    assert resp.status_code == 303, resp.text
    loc = resp.headers.get("location") or resp.headers.get("Location")
    assert loc and "/operator/runs/" in loc
    run_id = int(loc.rstrip("/").split("/")[-1])
    # detail shows evidence, process outcome, UNKNOWN task
    detail = client.get(f"/operator/runs/{run_id}")
    assert detail.status_code == 200
    assert f"Run #{run_id}" in detail.text
    # exit code present, process outcome badge, but task UNKNOWN
    assert "SUCCESS" in detail.text or "FAILURE" in detail.text
    # task outcome should be UNKNOWN (no scoring automation, exit 0 not success)
    # check that attempt row contains UNKNOWN for task outcome
    assert "UNKNOWN" in detail.text
    assert "badge-unknown" in detail.text
    # verify DB directly
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Run, Attempt
        run = s.get(Run, run_id)
        assert run is not None
        assert run.test_version_id == ids["tv_id"]
        assert run.model_id == ids["model_id"]
        # harness resolved
        assert run.harness_id is not None
        # capability preserved from version
        assert run.capability_id == ids["cap_id"]
        attempts = list(s.scalars(select(Attempt).where(Attempt.run_id==run_id)).all())
        assert len(attempts)==1
        a = attempts[0]
        assert a.exit_code is not None  # harness returns 0 via real configured adapter
        assert a.process_outcome is not None
        # crucial: do not treat exit 0 as task success
        assert a.task_outcome.value == "UNKNOWN"
        assert a.deliverable_outcome.value == "UNKNOWN"
        assert a.sealed_at is not None
        assert a.elapsed_seconds is not None
        assert a.raw_evidence_location is not None

def test_exit_zero_not_task_success(client):
    ids = _setup_evidence(client)
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":tok}, follow=False)
    run_id = int((resp.headers.get("location") or "").rstrip("/").split("/")[-1])
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Attempt
        a = s.scalar(select(Attempt).where(Attempt.run_id==run_id))
        assert a.exit_code == 0
        # even though exit 0, task outcome remains UNKNOWN, not SUCCEEDED
        assert a.task_outcome.value == "UNKNOWN"
    detail = client.get(f"/operator/runs/{run_id}").text
    # page should not present exit 0 as proof of pass
    assert "exit code" in detail.lower() or "Exit code" in detail
    # Ensure PASS badge not present when task UNKNOWN (only UNKNOWN badge)
    # latest_score should be UNKNOWN since no scoring automation
    assert "Not scored" in detail or "UNKNOWN" in detail

def test_unknown_stays_unknown(client):
    ids = _setup_evidence(client)
    # execution always keeps UNKNOWN for task/deliverable; verify via DB that UNKNOWN not coerced to PASS
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":tok}, follow=False)
    run_id = int((resp.headers.get("location") or "").rstrip("/").split("/")[-1])
    overview = client.get("/operator").text
    assert f'data-run-id="{run_id}"' in overview
    # overview should show UNKNOWN for unscored
    row = overview.split(f'data-run-id="{run_id}"')[1].split("</tr>")[0]
    assert "UNKNOWN" in row
    assert "badge-unknown" in row

def test_duplicate_prevention_idempotency(client):
    ids = _setup_evidence(client)
    token = "dup-token-12345"
    resp1 = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":token}, follow=False)
    assert resp1.status_code == 303
    loc1 = resp1.headers.get("location") or resp1.headers.get("Location")
    resp2 = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":token}, follow=False)
    assert resp2.status_code == 303
    loc2 = resp2.headers.get("location") or resp2.headers.get("Location")
    assert loc1 == loc2
    # only one run created
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Run
        cnt = s.scalar(select(sa.func.count(Run.id)).where(Run.idempotency_key==token))
        assert int(cnt)==1

def test_demo_provenance_structural_not_name_based(client):
    # seed demo via model flag
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        s.commit()
        # verify is_demo column set
        from aecc.models import Run
        demo_run = s.scalar(select(Run).where(Run.is_demo==True))
        assert demo_run is not None
        # name-based detection should not be used; create user data with same keys but is_demo=False
        # create user capability/model/run with same naming pattern but not demo
        from aecc.models import Capability, Harness, LogicalTest, Model, TestVersion
        h = Harness(harness_key="opencode-demo", display_name="demo-like", is_demo=False)
        # this harness key contains demo string but is_demo False, should not be considered demo
        s.add(h); s.flush()
        assert h.is_demo == False
        # check demo detection via column only
        cnt_demo = s.scalar(select(sa.func.count(Harness.id)).where(Harness.is_demo==True))
        cnt_user_demo_name = s.scalar(select(sa.func.count(Harness.id)).where(Harness.harness_key=="opencode-demo"))
        assert int(cnt_demo) >=1
        assert int(cnt_user_demo_name)==1
        # clearing demo should not delete user harness with demo-like name
        from aecc.demo import clear_demo_data
        clear_demo_data(s)
        remaining = s.get(Harness, h.id)
        assert remaining is not None, "user data with demo-like name incorrectly deleted"
        assert s.scalar(select(Run).where(Run.is_demo==True)) is None

def test_demo_labeled_and_excluded_from_real(client):
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        s.commit()
    overview = client.get("/operator").text
    # demo badge present
    assert "demo" in overview.lower()
    assert "badge-unknown" in overview
    # detail also labeled
    with factory() as s:
        from aecc.models import Run
        demo_id = s.scalar(select(Run.id).where(Run.is_demo==True))
    detail = client.get(f"/operator/runs/{demo_id}").text
    assert "demo" in detail.lower()
    assert "is_demo" in detail or "Demo evidence" in detail

def test_clear_demo_only_never_user(client):
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        s.commit()
        before_demo = s.scalar(select(sa.func.count(sa.text("1"))).select_from(sa.text("runs")).where(text("is_demo=1")) )  # type: ignore
    # create user run via execution
    ids = _setup_evidence(client)
    # need fresh token
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":tok}, follow=False)
    user_run_id = int((resp.headers.get("location") or "").rstrip("/").split("/")[-1])
    # clear demo via POST
    resp_clear = client.post("/operator/demo/clear", content="", headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=True)
    assert resp_clear.status_code == 200
    with factory() as s:
        from aecc.models import Run
        assert s.get(Run, user_run_id) is not None, "user run incorrectly cleared"
        demo_remaining = s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo==True))
        assert int(demo_remaining or 0)==0
    # no auto reseed
    overview = client.get("/operator").text
    # seed button should appear (no demo), but overview should still have user run
    assert f'data-run-id="{user_run_id}"' in overview
    assert "Load demo data" in overview

def test_no_automatic_reseed_after_removal(client):
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        s.commit()
    client.post("/operator/demo/clear", content="", headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=True)
    # second overview should not auto reseed demo
    overview2 = client.get("/operator").text
    assert "demo data" not in overview2.lower() or "Load demo data" in overview2
    with factory() as s:
        from aecc.models import Run
        assert s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo==True)) in (None,0)

def test_empty_start_and_seed_option(client):
    # fresh db is empty
    ov = client.get("/operator").text
    assert "No runs recorded yet" in ov
    assert "Load demo data" in ov
    # seed via POST
    resp = client.post("/operator/demo/seed", content="", headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=True)
    assert resp.status_code == 200
    ov2 = client.get("/operator").text
    assert "demo" in ov2.lower()
    assert "Remove demo data" in ov2

def test_execution_preserves_identities(client):
    ids = _setup_evidence(client)
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":tok}, follow=False)
    run_id = int((resp.headers.get("location") or "").rstrip("/").split("/")[-1])
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Run, TestVersion
        run = s.get(Run, run_id)
        tv = s.get(TestVersion, ids["tv_id"])
        assert run.test_version_id == tv.id
        assert run.source_commit == tv.source_commit
        assert run.permission_profile == tv.permission_profile

def test_permission_denial_captured_where_available(client, monkeypatch):
    # Real harness adapter: execution via opencode run should capture permission denial from stderr
    _setup_evidence(client)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Capability, Harness
        import json
        cap = s.scalar(select(Capability).where(Capability.capability_key=="exec.cap"))
        cap_id = cap.id
        from aecc.models import LogicalTest
        lt = s.scalar(select(LogicalTest).where(LogicalTest.key=="exec-test"))
        lt_id = lt.id
        # create a runnable opencode harness (adapter declaration required, version/build/mode alone insufficient)
        h = Harness(harness_key="perm-denied-harness", display_name="perm", config_snapshot=json.dumps({"adapter":"opencode"}), is_demo=False)
        s.add(h); s.flush(); hid = h.id
        s.commit()
    resp = _post(client, f"/operator/tests/{lt_id}/versions", {"capability_id":str(cap_id),"task_prompt":"do permission test real","acceptance_criteria":"a","rubric_id":"r","rubric_version":"1","permission_profile":"READ_ONLY_NO_SHELL"}, follow=False)
    # find new tv id
    with factory() as s:
        from aecc.models import TestVersion
        tv = s.scalar(select(TestVersion).where(TestVersion.logical_test_id==lt_id).order_by(TestVersion.version_number.desc()))
        tv_id_perm = tv.id
        from aecc.models import Model
        m = s.scalar(select(Model).where(Model.model_key=="exec-model"))
        mid = m.id
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    # Override the auto success mock for this specific run to return permission denied stderr
    monkeypatch.setattr("aecc.execution._run_harness_process", _mock_denied_run)
    resp2 = _post(client, "/operator/runs", {"test_version_id":str(tv_id_perm),"model_id":str(mid),"harness_id":str(hid),"idempotency_key":tok}, follow=False)
    assert resp2.status_code == 303, resp2.text
    run_id = int((resp2.headers.get("location") or "").rstrip("/").split("/")[-1])
    with factory() as s:
        from aecc.models import Attempt
        att = s.scalar(select(Attempt).where(Attempt.run_id==run_id))
        assert att.permission_denied == True
        assert att.permission_denial_evidence is not None
        assert "permission" in att.permission_denial_evidence.lower() or "denied" in att.permission_denial_evidence.lower()
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "permission-denied" in detail

def test_harness_not_configured_records_infra_not_fake(client):
    """If no runnable harness adapter is configured, execution must not fake evidence;
    it must record infrastructure/not-configured with UNKNOWN outcomes."""
    ids = _setup_evidence(client)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    # create an explicitly NOT-configured harness (no config_snapshot, no version)
    with factory() as s:
        from aecc.models import Harness
        h = Harness(harness_key="unconfigured-harness", display_name="unconfigured", version=None, build=None, config_snapshot=None, config_hash=None, is_demo=False)
        s.add(h); s.flush(); hid = h.id
        s.commit()
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"harness_id":str(hid),"idempotency_key":tok}, follow=False)
    assert resp.status_code == 303, resp.text
    run_id = int((resp.headers.get("location") or "").rstrip("/").split("/")[-1])
    with factory() as s:
        from aecc.models import Run, Attempt, RunState, ProcessOutcome
        run = s.get(Run, run_id)
        assert run is not None
        assert run.state == RunState.INFRASTRUCTURE_FAILURE, f"expected INFRASTRUCTURE_FAILURE, got {run.state}"
        att = s.scalar(select(Attempt).where(Attempt.run_id==run_id))
        assert att is not None
        # Must not fake exit code 0 as success; exit_code stays NULL, process UNKNOWN, task UNKNOWN
        assert att.exit_code is None
        assert att.process_outcome == ProcessOutcome.UNKNOWN
        assert att.task_outcome.value == "UNKNOWN"
        assert att.deliverable_outcome.value == "UNKNOWN"
        assert "not-configured" in (att.invocation_meta or "").lower() or "not-configured" in (att.raw_evidence_location or "").lower() or "not-configured" in (att.stderr if hasattr(att, 'stderr') else "") or "harness not configured" in (att.invocation_meta or "")
        # ensure not treated as pass
        assert att.task_outcome.value != "SUCCEEDED"
    detail = client.get(f"/operator/runs/{run_id}").text
    # infra badge should be visible, not pass
    assert "INFRASTRUCTURE_FAILURE" in detail or "badge-infra" in detail or "not-configured" in detail.lower()
    assert "badge-pass" not in detail or "UNKNOWN" in detail


def test_null_capability_version_refuses_execution(client):
    """Never infer capability identity when TestVersion.capability_version is NULL;
    execution must refuse and UNKNOWN stays UNKNOWN (no Run created)."""
    _setup_evidence(client)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from datetime import datetime, timezone
        from aecc.models import Capability, LogicalTest, TestVersion
        from aecc.hashing import build_definition_payload, canonical_definition_hash
        cap = s.scalar(select(Capability).where(Capability.capability_key=="exec.cap"))
        lt = s.scalar(select(LogicalTest).where(LogicalTest.key=="exec-test"))
        # Create a TestVersion with NULL capability_version directly (bypassing UI validation)
        payload = build_definition_payload(task_prompt="null version task", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", capability_key=cap.capability_key, capability_version=None)
        now = datetime.now(timezone.utc)
        tv_null = TestVersion(logical_test_id=lt.id, version_number=999, task_prompt="null version task", capability_key=cap.capability_key, capability_version=None, acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", created_at=now, registered_at=now, definition_hash=canonical_definition_hash(payload))
        s.add(tv_null); s.flush(); tv_null_id = tv_null.id
        from aecc.models import Model
        m = s.scalar(select(Model).where(Model.model_key=="exec-model"))
        mid = m.id
        s.commit()
        # Also count runs before
        from aecc.models import Run
        before_cnt = s.scalar(select(sa.func.count(Run.id)))
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    resp = _post(client, "/operator/runs", {"test_version_id":str(tv_null_id),"model_id":str(mid),"idempotency_key":tok}, follow=False)
    # Should be refused with 400, not 303, and no new run with that version
    assert resp.status_code == 400, f"expected refusal 400, got {resp.status_code}: {resp.text}"
    assert "capability_version" in resp.text.lower() or "unknown" in resp.text.lower()
    with factory() as s:
        from aecc.models import Run
        after_cnt = s.scalar(select(sa.func.count(Run.id)))
        assert int(after_cnt) == int(before_cnt), "refused execution must not create a Run"
        # Direct service call must also raise
        from aecc.execution import execute_run
        with pytest.raises(ValueError, match="capability_version NULL.*UNKNOWN"):
            execute_run(s, test_version_id=tv_null_id, model_id=mid, idempotency_key="direct-null-test")

def test_idempotency_key_reuse_with_different_parameters_is_refused(client):
    """Same key must never silently alias a different evaluation."""
    ids = _setup_evidence(client)
    # second model
    _post(client, "/operator/models", {"model_key":"exec-model-2","provider":"test-prov","exact_identifier":"test-prov/exec-2","pricing_tier":"free","is_active":"on"}, follow=True)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Model, Run
        m2 = s.scalar(select(Model).where(Model.model_key=="exec-model-2")).id
    token = "reuse-token-1"
    r1 = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":token})
    assert r1.status_code == 303
    r2 = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(m2),"idempotency_key":token})
    assert r2.status_code == 400, r2.text
    assert "different parameters" in r2.text
    with factory() as s:
        from aecc.models import Run
        assert s.scalar(select(sa.func.count(Run.id)).where(Run.idempotency_key==token)) == 1
        assert s.scalar(select(sa.func.count(Run.id)).where(Run.model_id==m2)) == 0


def test_real_run_never_binds_to_demo_harness(client):
    """A non-demo run must not reference demo entities: explicit demo harness is
    refused, and auto-selection skips demo harnesses even when they are the
    only runnable ones."""
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    import json
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        from aecc.models import Harness
        demo_h = s.scalar(select(Harness).where(Harness.is_demo==True))
        demo_h.config_snapshot = json.dumps({"adapter":"opencode"})  # runnable, but demo
        demo_hid = demo_h.id
        s.commit()
    ids = _setup_evidence(client)  # creates a distinct non-demo runnable harness
    with factory() as s:
        from aecc.models import Harness
        # remove the non-demo harness so only the demo one is runnable
        for h in s.scalars(select(Harness).where(Harness.is_demo==False)).all():
            s.delete(h)
        s.commit()
    r = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"harness_id":str(demo_hid),"idempotency_key":"demo-mix-1"})
    assert r.status_code == 400 and "provenance mismatch" in r.text
    r = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":"demo-mix-2"})
    assert r.status_code == 400 and "no harness available" in r.text
    with factory() as s:
        from aecc.models import Run
        assert s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo==False)) == 0
    # and demo removal still works because nothing real points at demo rows
    resp_clear = client.post("/operator/demo/clear", content="", follow_redirects=False)
    assert resp_clear.status_code == 303


def test_clear_demo_refuses_when_real_evidence_references_demo(client):
    """If a non-demo row references a demo row, nothing is deleted (409)."""
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        from aecc.models import Run, Harness
        demo_run = s.scalar(select(Run).where(Run.is_demo==True))
        # simulate legacy/bad data: a real run pointing at a demo harness
        real = Run(test_version_id=demo_run.test_version_id, harness_id=demo_run.harness_id, model_id=demo_run.model_id, capability_id=demo_run.capability_id, is_demo=False, idempotency_key="legacy-real-1")
        s.add(real); s.commit(); real_id = real.id
        demo_count = s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo==True))
    resp = client.post("/operator/demo/clear", content="", follow_redirects=False)
    assert resp.status_code == 409
    with factory() as s:
        from aecc.models import Run
        assert s.get(Run, real_id) is not None
        assert s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo==True)) == demo_count, "partial demo deletion must not happen"


def test_real_subprocess_boundary_via_fake_opencode(client, fake_opencode, monkeypatch):
    """Not a mock: a real child process records argv/cwd/env. Proves the web
    path spawns the harness in the isolated workspace, with the permission
    policy injected, `--` before the prompt, and evidence persisted."""
    import json, os, shutil
    # undo the autouse mocks so the real subprocess is used
    monkeypatch.setattr("aecc.execution._run_harness_process", _REAL_RUN_HARNESS_PROCESS)
    monkeypatch.setattr("aecc.execution._is_opencode_available", lambda: shutil.which("opencode") is not None)
    record = fake_opencode(exit_code=3, stdout="model said hi", stderr="warn")
    ids = _setup_evidence(client)
    resp = _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":"real-sub-1"})
    assert resp.status_code == 303, resp.text
    run_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
    rec = json.loads(record.read_text())
    runs_root = Path(os.environ["AECC_RUNS_ROOT"]).resolve()
    ws = runs_root / str(run_id) / "workspace"
    assert Path(rec["cwd"]).resolve() == ws
    assert rec["argv"][:2] == ["run", "--dir"]
    assert Path(rec["argv"][2]).resolve() == ws
    assert rec["argv"][3:5] == ["--agent", "aecc-eval"]
    assert rec["argv"][5:7] == ["--model", "test-prov/exec-1"]
    assert rec["argv"][7] == "--" and rec["argv"][8] == "do exec thing"
    assert "--auto" not in rec["argv"]
    cfg = json.loads(rec["env"]["OPENCODE_CONFIG_CONTENT"])
    policy = cfg["permission"]
    assert policy["edit"] == "deny" and policy["bash"] == "deny"
    assert policy["webfetch"] == "deny" and policy["websearch"] == "deny"
    assert policy["external_directory"] == "deny"
    assert policy["task"] == "deny" and policy["skill"] == "deny"
    assert policy["*"] == "deny"
    assert "aecc-eval" in cfg["agent"]
    assert rec["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    # workspace is outside the repo and not inside a git worktree
    assert not str(ws).startswith(str(ROOT.resolve()))
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Attempt, ProcessOutcome, RunState, Run
        a = s.scalar(select(Attempt).where(Attempt.run_id==run_id))
        assert a.exit_code == 3 and a.process_outcome == ProcessOutcome.FAILURE
        assert a.task_outcome.value == "UNKNOWN"
        assert s.get(Run, run_id).state == RunState.COMPLETED
        ev = Path(a.raw_evidence_location)
        assert ev.is_dir() and ev.resolve() == (runs_root / str(run_id) / "a1").resolve()
        assert (ev / "stdout.txt").read_text() == "model said hi"
        assert (ev / "stderr.txt").read_text() == "warn"
        inv = json.loads((ev / "invocation.json").read_text())
        assert inv["model_exact_identifier"] == "test-prov/exec-1" and inv["permission_profile"] == "READ_ONLY_NO_SHELL"
        # AECC wrote nothing into the subject workspace
        assert list(ws.iterdir()) == []


def test_write_or_shell_profile_refused_on_host_adapter(client):
    """Host subprocess is not OS containment: write/shell profiles must be
    recorded as INFRASTRUCTURE_FAILURE, never executed (ARCH §9.5)."""
    ids = _setup_evidence(client)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import LogicalTest, Capability
        lt_id = s.scalar(select(LogicalTest).where(LogicalTest.key=="exec-test")).id
        cap_id = s.scalar(select(Capability).where(Capability.capability_key=="exec.cap")).id
    _post(client, f"/operator/tests/{lt_id}/versions", {"capability_id":str(cap_id),"task_prompt":"write stuff","acceptance_criteria":"a","rubric_id":"r","rubric_version":"1","permission_profile":"WORKSPACE_WRITE_AND_SHELL_CONTAINED"})
    with factory() as s:
        from aecc.models import TestVersion
        tv_id = s.scalar(select(TestVersion).where(TestVersion.task_prompt=="write stuff")).id
    calls = []
    with mock.patch("aecc.execution._run_harness_process", side_effect=lambda *a, **k: calls.append(a)):
        resp = _post(client, "/operator/runs", {"test_version_id":str(tv_id),"model_id":str(ids["model_id"]),"idempotency_key":"write-prof-1"})
    assert resp.status_code == 303
    assert calls == [], "harness must not be spawned for a non-enforceable profile"
    run_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
    with factory() as s:
        from aecc.models import Run, Attempt, RunState
        assert s.get(Run, run_id).state == RunState.INFRASTRUCTURE_FAILURE
        a = s.scalar(select(Attempt).where(Attempt.run_id==run_id))
        assert "requires OS/container containment" in (a.invocation_meta or "")


def test_sealed_attempt_immutability_for_user(client):
    ids = _setup_evidence(client)
    html = client.get("/operator/runs/new").text
    import re
    tok = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
    _post(client, "/operator/runs", {"test_version_id":str(ids["tv_id"]),"model_id":str(ids["model_id"]),"idempotency_key":tok}, follow=False)
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        from aecc.models import Attempt
        att = s.scalar(select(Attempt))
        aid = att.id
        # try to update sealed attempt (is_demo=False) -> should raise
        with pytest.raises(sa.exc.DBAPIError):
            with s.bind.connect() as conn:
                with conn.begin():
                    conn.execute(text("UPDATE attempts SET exit_code=99 WHERE id=:i"), {"i": aid})


# ---------------------------------------------------------------------------
# R2 hardening: provenance immutability, demo ordering, idempotent seeding
# ---------------------------------------------------------------------------

def test_is_demo_provenance_cannot_be_relabeled(client):
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    from aecc.models import Run
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_dashboard_data(s, is_demo=True)
        s.commit()
        demo_run = s.scalar(select(Run).where(Run.is_demo == True))  # noqa: E712
        rid = demo_run.id
    with factory() as s:
        # Laundering demo evidence into real evidence must be impossible.
        with pytest.raises(sa.exc.DBAPIError):
            with s.bind.connect() as conn:
                with conn.begin():
                    conn.execute(text("UPDATE runs SET is_demo=0 WHERE id=:i"), {"i": rid})
    with factory() as s:
        assert s.get(Run, rid).is_demo is True


def test_clear_demo_handles_audit_referencing_qualification(client):
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    from aecc.models import AuditEvent, Run
    from aecc.demo import clear_demo_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        info = seed_dashboard_data(s, is_demo=True)
        # An audit event referencing a demo qualification decision must not
        # block (or be orphaned by) demo removal: audit is deleted before quals.
        s.add(AuditEvent(action="demo_audit", run_id=info["runs"]["r1"], qualification_id=info["quals"]["q1b"], is_demo=True))
        s.commit()
        assert int(s.scalar(select(sa.func.count(AuditEvent.id)).where(AuditEvent.is_demo == True)) or 0) >= 1  # noqa: E712
    with factory() as s:
        clear_demo_data(s)
        assert int(s.scalar(select(sa.func.count(Run.id)).where(Run.is_demo == True)) or 0) == 0  # noqa: E712


def test_seed_demo_data_is_idempotent(client):
    from aecc.db import create_session_factory
    from aecc.demo import count_demo_rows, seed_demo_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        seed_demo_data(s)
        first = count_demo_rows(s)
    with factory() as s:
        seed_demo_data(s)
        second = count_demo_rows(s)
    assert sum(first.values()) > 0
    assert first == second, "seeding demo twice must not duplicate or relabel rows"
