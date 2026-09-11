"""Unit tests for OpenCode harness adapter.

Verifies command construction uses Model.exact_identifier and TestVersion prompt,
uses subprocess argv (not shell), wires --dir with per-run isolated workspace,
and handles preflight / failure paths. Also proves the adapter cannot execute
in the AECC repo root or an unspecified cwd.
"""

import json
import subprocess
from unittest import mock

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cfg(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


def _engine(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "adapter.sqlite"
    command.upgrade(_cfg(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas
    apply_sqlite_pragmas(engine)
    return engine


def _make_harness_model_tv(session):
    from aecc.models import Capability, Harness, LogicalTest, Model, TestVersion
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    from datetime import datetime, timezone
    cap = Capability(capability_key="adapter.cap", version="v1", is_active=True)
    session.add(cap); session.flush()
    h = Harness(harness_key="opencode", display_name="opencode", config_snapshot=json.dumps({"adapter": "opencode"}), is_demo=False)
    session.add(h); session.flush()
    m = Model(model_key="adapter-model", provider="opencode", exact_identifier="opencode/test-model-1", is_active=True)
    session.add(m); session.flush()
    lt = LogicalTest(key="adapter-test", name="Adapter Test")
    session.add(lt); session.flush()
    payload = build_definition_payload(task_prompt="do adapter thing", acceptance_criteria="must do", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", capability_key=cap.capability_key, capability_version=cap.version)
    tv = TestVersion(logical_test_id=lt.id, version_number=1, task_prompt="do adapter thing", capability_key=cap.capability_key, capability_version=cap.version, acceptance_criteria="must do", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
    session.add(tv); session.flush()
    return h, m, tv


def _safe_workspace(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _tv_variant(session, *, task_prompt="do adapter thing", permission_profile="READ_ONLY_NO_SHELL", source_fixture_ref=None, source_commit=None):
    """Register a second, distinct TestVersion (versions are immutable, so tests
    must register variants rather than mutate). Returns (harness, model, tv)."""
    from aecc.models import TestVersion
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    from datetime import datetime, timezone
    h, m, tv0 = _make_harness_model_tv(session)
    payload = build_definition_payload(task_prompt=task_prompt, acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile=permission_profile, capability_key="adapter.cap", capability_version="v1", source_fixture_ref=source_fixture_ref, source_commit=source_commit)
    tv = TestVersion(logical_test_id=tv0.logical_test_id, version_number=2, task_prompt=task_prompt, capability_key="adapter.cap", capability_version="v1", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile=permission_profile, source_fixture_ref=source_fixture_ref, source_commit=source_commit, created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
    session.add(tv); session.flush()
    session.commit()
    return h, m, tv


def test_build_opencode_command_uses_exact_identifier_and_prompt(tmp_path):
    from aecc.execution import build_opencode_command
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws1")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        cmd = build_opencode_command(tv, m, workspace=ws)
        assert isinstance(cmd, list)
        assert cmd[0] == "opencode"
        assert cmd[1] == "run"
        # must contain --dir with isolated workspace
        assert "--dir" in cmd
        idx_dir = cmd.index("--dir")
        assert cmd[idx_dir + 1] == str(ws)
        # must contain --model and exact identifier
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx+1] == m.exact_identifier
        # prompt must be the last element, preceded by `--` so a prompt that
        # starts with '-' can never be parsed as a flag
        assert cmd[-1] == tv.task_prompt
        assert cmd[-2] == "--"
        assert "--auto" not in cmd
        # --dir must appear before --model
        assert idx_dir < idx
        # no shell string, no echo/sleep
        joined = " ".join(cmd)
        assert "echo" not in joined
        assert "sleep" not in joined
        s.rollback()
    engine.dispose()


def test_build_opencode_command_raises_if_missing_identifier(tmp_path):
    from aecc.execution import build_opencode_command
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws2")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        m.exact_identifier = ""
        with pytest.raises(ValueError, match="exact_identifier"):
            build_opencode_command(tv, m, workspace=ws)
        m.exact_identifier = "opencode/x"
        tv.task_prompt = "   "
        with pytest.raises(ValueError, match="prompt"):
            build_opencode_command(tv, m, workspace=ws)
        s.rollback()
    engine.dispose()


def test_build_opencode_command_requires_workspace(tmp_path):
    """Permanent safety test: adapter must refuse unspecified workspace/cwd."""
    from aecc.execution import build_opencode_command
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        # No workspace -> must raise
        with pytest.raises(ValueError, match="workspace required"):
            build_opencode_command(tv, m)
        with pytest.raises(ValueError, match="workspace required"):
            build_opencode_command(tv, m, workspace=None)
        with pytest.raises(ValueError, match="workspace required"):
            build_opencode_command(tv, m, workspace="")
        with pytest.raises(ValueError, match="workspace required"):
            build_opencode_command(tv, m, workspace="   ")
        s.rollback()
    engine.dispose()


def test_build_opencode_command_refuses_aecc_repo_workspace(tmp_path):
    """Permanent safety test: adapter must never execute in AECC repo root."""
    from aecc.execution import build_opencode_command
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        # AECC repo root must be refused
        with pytest.raises(ValueError, match="(AECC repo|workspace)"):
            build_opencode_command(tv, m, workspace=ROOT)
        with pytest.raises(ValueError, match="(AECC repo|workspace)"):
            build_opencode_command(tv, m, workspace=str(ROOT))
        # filesystem root also refused
        with pytest.raises(ValueError, match="workspace"):
            build_opencode_command(tv, m, workspace="/")
        s.rollback()
    engine.dispose()


def test_is_harness_runnable_requires_adapter_not_version_build_mode(tmp_path):
    from aecc.execution import is_harness_runnable
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    from aecc.models import Harness
    with factory() as s:
        h1 = Harness(harness_key="h1", config_snapshot=None, version=None, build=None)
        assert is_harness_runnable(h1) is False
        h2 = Harness(harness_key="h2", version="1.4.2", build="build-1", config_snapshot='{"mode":"contained"}', config_hash="cfg")
        assert is_harness_runnable(h2) is False
        h3 = Harness(harness_key="h3", config_snapshot='{"mode":"contained"}')
        assert is_harness_runnable(h3) is False
        h4 = Harness(harness_key="h4", version="1.0", config_hash="cfg-perm", config_snapshot='{"mode":"restricted"}')
        assert is_harness_runnable(h4) is False
        h5 = Harness(harness_key="opencode", config_snapshot=json.dumps({"adapter":"opencode"}))
        assert is_harness_runnable(h5) is True
        h6 = Harness(harness_key="opencode", config_snapshot=json.dumps({"opencode_adapter": True}))
        assert is_harness_runnable(h6) is True
        h7 = Harness(harness_key="evil", config_snapshot=json.dumps({"command":"echo pwn"}))
        assert is_harness_runnable(h7) is False
        s.rollback()
    engine.dispose()


def test_check_preflight_fails_when_binary_missing(tmp_path):
    from aecc.execution import check_preflight
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_preflight1")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        with mock.patch("aecc.execution._is_opencode_available", return_value=False):
            err = check_preflight(h, m, tv, workspace=ws)
            assert err is not None
            assert "opencode binary" in err.lower()
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            err = check_preflight(h, m, tv, workspace=ws)
            assert err is None
        s.rollback()
    engine.dispose()


def test_check_preflight_fails_when_harness_not_configured(tmp_path):
    from aecc.execution import check_preflight
    from aecc.models import Harness
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_preflight2")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        bad = Harness(harness_key="unconfigured", config_snapshot=None)
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            err = check_preflight(bad, m, tv, workspace=ws)
            assert err is not None
            assert "harness not configured" in err.lower()
            assert "not-configured" not in err
        s.rollback()
    engine.dispose()


def test_check_preflight_refuses_unsafe_workspace(tmp_path):
    """Permanent safety test: preflight must require explicit isolated workspace."""
    from aecc.execution import check_preflight
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            # unspecified workspace refused
            err = check_preflight(h, m, tv, workspace=None)
            assert err is not None
            assert "workspace" in err.lower()
            err2 = check_preflight(h, m, tv, workspace="")
            assert err2 is not None
            assert "workspace" in err2.lower()
            # AECC repo root refused
            err3 = check_preflight(h, m, tv, workspace=ROOT)
            assert err3 is not None
            assert "workspace" in err3.lower() or "repo" in err3.lower()
            # safe workspace passes
            ws = _safe_workspace(tmp_path, "ws_preflight_safe")
            err4 = check_preflight(h, m, tv, workspace=ws)
            assert err4 is None
        s.rollback()
    engine.dispose()


def test_run_harness_subprocess_uses_argv_not_shell(tmp_path):
    from aecc.execution import run_harness_subprocess
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_run1")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=["opencode","run"], returncode=0, stdout="ok", stderr="")
                result = run_harness_subprocess(tv, h, m, timeout_seconds=5, workspace=ws)
                assert mock_run.called
                call_kwargs = mock_run.call_args.kwargs
                call_args = mock_run.call_args.args
                argv = call_args[0] if call_args else call_kwargs.get("argv")
                assert isinstance(argv, list)
                assert argv[0] == "opencode"
                assert "--dir" in argv
                idx_dir = argv.index("--dir")
                assert argv[idx_dir+1] == str(ws)
                assert "--agent" in argv
                assert argv[argv.index("--agent") + 1] == "aecc-eval"
                assert "--model" in argv
                assert m.exact_identifier in argv
                assert tv.task_prompt in argv
                assert "shell" not in call_kwargs
                # cwd must be workspace, not repo
                assert "cwd" in call_kwargs
                assert Path(call_kwargs["cwd"]).resolve() == ws.resolve()
                assert result.exit_code == 0
        s.rollback()
    engine.dispose()


def test_run_harness_subprocess_no_shell_or_echo(tmp_path):
    """Ensure code does not contain shell=True simulation and uses --dir."""
    import pathlib
    src = pathlib.Path(ROOT / "src/aecc/execution.py").read_text()
    assert "shell=True" not in src
    assert "echo 'executing" not in src
    assert "sleep 0.02" not in src
    assert "opencode" in src
    assert "build_opencode_command" in src or "opencode\", \"run\"" in src
    assert "--dir" in src
    # ensure workspace validation appears
    assert "workspace" in src.lower()
    assert "_validate_workspace" in src or "workspace required" in src


def test_run_harness_subprocess_returns_not_configured_when_preflight_fails(tmp_path):
    from aecc.execution import run_harness_subprocess
    from aecc.models import Harness
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_run2")
    with factory() as s:
        bad = Harness(harness_key="bad", config_snapshot=None)
        _, m, tv = _make_harness_model_tv(s)
        result = run_harness_subprocess(tv, bad, m, workspace=ws)
        assert result.error == "not-configured"
        assert result.exit_code is None
        assert "harness not configured" in result.stderr.lower()
        h_good = s.scalar(sa.select(Harness).where(Harness.harness_key=="opencode"))
        with mock.patch("aecc.execution._is_opencode_available", return_value=False):
            result2 = run_harness_subprocess(tv, h_good, m, workspace=ws)
            assert result2.error == "not-configured"
            assert "opencode binary" in result2.stderr.lower()
        s.rollback()
    engine.dispose()


def test_run_harness_subprocess_refuses_unsafe_workspace(tmp_path):
    """Permanent safety test: subprocess must not run in AECC repo or unspecified cwd."""
    from aecc.execution import run_harness_subprocess
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mrun:
                mrun.return_value = subprocess.CompletedProcess(args=["opencode"], returncode=0, stdout="ok", stderr="")
                # No workspace -> not-configured, no subprocess call
                r1 = run_harness_subprocess(tv, h, m, workspace=None)
                assert r1.error == "not-configured"
                assert "workspace" in r1.stderr.lower()
                assert mrun.call_count == 0
                # AECC repo -> refused
                r2 = run_harness_subprocess(tv, h, m, workspace=ROOT)
                assert r2.error == "not-configured"
                assert "workspace" in r2.stderr.lower() or "repo" in r2.stderr.lower()
                assert mrun.call_count == 0
                # Safe workspace -> allowed
                ws = _safe_workspace(tmp_path, "ws_safe_run")
                r3 = run_harness_subprocess(tv, h, m, workspace=ws)
                assert r3.error is None
                assert r3.exit_code == 0
                assert mrun.call_count == 1
        s.rollback()
    engine.dispose()


def test_run_harness_subprocess_handles_timeout(tmp_path):
    from aecc.execution import run_harness_subprocess
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_timeout")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process", side_effect=subprocess.TimeoutExpired(cmd=["opencode"], timeout=1, output=b"", stderr=b"timeout")):
                result = run_harness_subprocess(tv, h, m, timeout_seconds=1, workspace=ws)
                assert result.timed_out is True
                assert result.error == "timeout"
        s.rollback()
    engine.dispose()


def test_execute_run_records_infra_failure_on_preflight_and_preserves_unknown(tmp_path):
    from aecc.execution import execute_run
    from aecc.models import Harness, RunState, ProcessOutcome
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        h.config_snapshot = json.dumps({"mode":"contained"})
        s.add(h); s.flush()
        from sqlalchemy import select
        from aecc.models import Capability
        cap = s.scalar(select(Capability).where(Capability.capability_key=="adapter.cap"))
        s.commit()
        with factory() as s2:
            tv2 = s2.get(tv.__class__, tv.id)
            m2 = s2.get(m.__class__, m.id)
            h2 = s2.get(Harness, h.id)
            ws = _safe_workspace(tmp_path, "ws_infra")
            with mock.patch("aecc.execution._is_opencode_available", return_value=True):
                run, attempt, result = execute_run(s2, test_version_id=tv2.id, model_id=m2.id, harness_id=h2.id, idempotency_key="infra-test-1", workspace=ws)
                assert run.state == RunState.INFRASTRUCTURE_FAILURE
                assert attempt.process_outcome == ProcessOutcome.UNKNOWN
                assert attempt.task_outcome.value == "UNKNOWN"
                assert attempt.deliverable_outcome.value == "UNKNOWN"
                assert attempt.exit_code is None
                assert result.error == "not-configured"
    engine.dispose()


def test_execute_run_no_placeholder_creation(tmp_path):
    """Ensure execute_run does not auto-create harness when none exists."""
    from aecc.execution import execute_run
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    from aecc.models import Capability, LogicalTest, Model, TestVersion, Harness
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    from datetime import datetime, timezone
    ws = _safe_workspace(tmp_path, "ws_noplace")
    with factory() as s:
        cap = Capability(capability_key="noharness.cap", version="v1", is_active=True)
        s.add(cap); s.flush()
        m = Model(model_key="noharness-model", provider="p", exact_identifier="p/m", is_active=True)
        s.add(m); s.flush()
        lt = LogicalTest(key="noharness-test", name="nht")
        s.add(lt); s.flush()
        payload = build_definition_payload(task_prompt="t", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", capability_key=cap.capability_key, capability_version=cap.version)
        tv = TestVersion(logical_test_id=lt.id, version_number=1, task_prompt="t", capability_key=cap.capability_key, capability_version=cap.version, acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
        s.add(tv); s.flush()
        s.query(Harness).delete()
        s.commit()
        with pytest.raises(ValueError, match="no harness available"):
            execute_run(s, test_version_id=tv.id, model_id=m.id, idempotency_key="noharness-1", workspace=ws)
        assert s.scalar(sa.select(sa.func.count(Harness.id))) == 0
    engine.dispose()


def test_execute_run_keeps_capability_version_enforcement(tmp_path):
    from aecc.execution import execute_run
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_capver")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        from aecc.models import LogicalTest, TestVersion
        from aecc.hashing import build_definition_payload, canonical_definition_hash
        from datetime import datetime, timezone
        lt = s.get(LogicalTest, tv.logical_test_id)
        payload = build_definition_payload(task_prompt="null", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", capability_key="adapter.cap", capability_version=None)
        tv_null = TestVersion(logical_test_id=lt.id, version_number=99, task_prompt="null", capability_key="adapter.cap", capability_version=None, acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="P", created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
        s.add(tv_null); s.flush()
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with pytest.raises(ValueError, match="capability_version NULL.*UNKNOWN"):
                execute_run(s, test_version_id=tv_null.id, model_id=m.id, harness_id=h.id, idempotency_key="cap-null-1", workspace=ws)
        s.rollback()
    engine.dispose()


def test_worker_calls_adapter_rather_than_simulation(tmp_path):
    """Integration-safe test: proves worker calls adapter with argv, --dir, not echo/sleep."""
    from aecc.execution import execute_run
    from aecc.models import RunState
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    ws = _safe_workspace(tmp_path, "ws_worker")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        s.commit()
    with factory() as s:
        from sqlalchemy import select
        from aecc.models import Harness, Model, TestVersion
        h = s.scalar(select(Harness).where(Harness.harness_key=="opencode"))
        m = s.scalar(select(Model).where(Model.model_key=="adapter-model"))
        tv = s.scalar(select(TestVersion).where(TestVersion.task_prompt=="do adapter thing"))
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mrun:
                mrun.return_value = subprocess.CompletedProcess(args=["opencode"], returncode=0, stdout="adapter output", stderr="")
                run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="adapter-proof-1", workspace=ws)
                assert mrun.call_count == 1
                argv = mrun.call_args.args[0]
                assert argv == ["opencode", "run", "--dir", str(ws.resolve()), "--agent", "aecc-eval", "--model", m.exact_identifier, "--", tv.task_prompt]
                kw = mrun.call_args.kwargs
                assert "shell" not in kw
                assert Path(kw["cwd"]).resolve() == ws.resolve()
                policy = json.loads(kw["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]
                assert policy["external_directory"] == "deny" and policy["bash"] == "deny" and policy["edit"] == "deny" and policy["*"] == "deny"
                assert run.state == RunState.COMPLETED
                assert result.exit_code == 0
                assert "echo" not in (attempt.invocation_meta or "")
                assert "sleep" not in (attempt.invocation_meta or "")
                meta = json.loads(attempt.invocation_meta)
                assert meta["argv"] == argv
                assert meta["workspace"] == str(ws)
                assert meta["model_exact_identifier"] == m.exact_identifier
                assert meta["capability"] == {"key": "adapter.cap", "version": "v1"}
                # AECC must not write anything into the subject workspace
                assert list(ws.iterdir()) == []
                # evidence persisted outside the workspace
                ev = Path(attempt.raw_evidence_location)
                assert (ev / "stdout.txt").read_text() == "adapter output"
                assert json.loads((ev / "invocation.json").read_text())["argv"] == argv
    engine.dispose()


def test_execute_run_refuses_aecc_repo_workspace(tmp_path):
    """Permanent safety test: execute_run must refuse AECC repo as workspace."""
    from aecc.execution import execute_run
    from aecc.models import RunState
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        s.commit()
    with factory() as s:
        from sqlalchemy import select
        from aecc.models import Harness, Model, TestVersion
        h = s.scalar(select(Harness).where(Harness.harness_key=="opencode"))
        m = s.scalar(select(Model).where(Model.model_key=="adapter-model"))
        tv = s.scalar(select(TestVersion).where(TestVersion.task_prompt=="do adapter thing"))
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mrun:
                mrun.return_value = subprocess.CompletedProcess(args=["opencode"], returncode=0, stdout="ok", stderr="")
                run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="repo-refuse-1", workspace=ROOT)
                assert result.error == "not-configured"
                assert "workspace" in result.stderr.lower() or "repo" in result.stderr.lower()
                assert run.state == RunState.INFRASTRUCTURE_FAILURE
                assert attempt.process_outcome.value == "UNKNOWN"
                # must not have invoked subprocess
                assert mrun.call_count == 0
                # invocation_meta must record the refused workspace
                meta = json.loads(attempt.invocation_meta)
                assert "workspace" in meta
    engine.dispose()


# ---------------------------------------------------------------------------
# Containment: a different cwd is not isolation
# ---------------------------------------------------------------------------

def test_workspace_under_aecc_repo_is_refused(tmp_path):
    """Permanent safety test: OpenCode adopts the enclosing git worktree as its
    project, so any directory under the AECC repository is NOT isolated."""
    from aecc.execution import _validate_workspace
    for candidate in (ROOT / "runs" / "999" / "workspace", ROOT / "src", ROOT / "data", ROOT / "tests"):
        err = _validate_workspace(candidate)
        assert err is not None and "inside the AECC repository" in err, candidate
    # an ancestor that *contains* the repo is refused too (or is '/', also refused)
    err = _validate_workspace(ROOT.parent)
    assert err is not None and ("contains the AECC repository" in err or "filesystem root" in err)
    # the operator's home is refused
    err = _validate_workspace(Path.home())
    assert err is not None
    # a directory that contains the evidence DB is refused
    db_parent = Path(__import__("os").environ.get("AECC_DB_PATH", str(ROOT / "data" / "evaluations.sqlite"))).parent
    assert _validate_workspace(db_parent) is not None


def test_workspace_nested_in_foreign_git_worktree_is_refused(tmp_path):
    repo = tmp_path / "somerepo"
    (repo / ".git").mkdir(parents=True)
    ws = repo / "sub" / "ws"
    ws.mkdir(parents=True)
    from aecc.execution import _validate_workspace
    err = _validate_workspace(ws)
    assert err is not None and "nested inside git worktree" in err


def test_non_empty_workspace_is_refused_but_prepared_workspace_passes(tmp_path):
    from aecc.execution import _validate_workspace
    ws = _safe_workspace(tmp_path, "dirty")
    (ws / "leftover.txt").write_text("from a previous run")
    err = _validate_workspace(ws)
    assert err is not None and "not empty" in err
    assert _validate_workspace(ws, require_fresh=False) is None


def test_default_workspace_is_outside_repo_under_runs_root(tmp_path, fake_opencode):
    """execute_run without an explicit workspace must use AECC_RUNS_ROOT/<run_id>/workspace,
    never the repository, and the real child process must run there."""
    import os
    from aecc.execution import execute_run
    record = fake_opencode(exit_code=0, stdout="ok")
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        s.commit()
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="default-ws-1")
        assert result.error is None and result.exit_code == 0
        rec = json.loads(record.read_text())
        expected = (Path(os.environ["AECC_RUNS_ROOT"]) / str(run.id) / "workspace").resolve()
        assert Path(rec["cwd"]).resolve() == expected
        assert not str(expected).startswith(str(ROOT.resolve()))
        assert not (ROOT / "runs" / str(run.id)).exists()
    engine.dispose()


def test_prompt_starting_with_dash_is_not_parsed_as_flag(tmp_path, fake_opencode):
    from aecc.execution import execute_run
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_variant(s, task_prompt="--version")
        ws = _safe_workspace(tmp_path, "dash")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="dash-1", workspace=ws)
        rec = json.loads(record.read_text())
        assert rec["argv"][-2:] == ["--", "--version"]
    engine.dispose()


# ---------------------------------------------------------------------------
# Permission profiles are server-owned and only enforceable ones run
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", ["WORKSPACE_WRITE_AND_SHELL_CONTAINED", "WORKSPACE_WRITE_RESTRICTED", "READ_ONLY_DIAGNOSTIC", "P", "READ_ONLY", ""])
def test_non_enforceable_profile_is_infra_failure_not_executed(tmp_path, profile):
    from aecc.execution import execute_run
    from aecc.models import RunState
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_variant(s, permission_profile=profile)
        ws = _safe_workspace(tmp_path, "prof")
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mrun:
                run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key=f"prof-{profile}", workspace=ws)
                assert mrun.call_count == 0
                assert run.state == RunState.INFRASTRUCTURE_FAILURE
                assert result.error == "not-configured"
                assert "permission profile" in result.stderr
    engine.dispose()


# ---------------------------------------------------------------------------
# Source materialization is exact or refused
# ---------------------------------------------------------------------------

def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _make_git_fixture(fixtures_root: Path, name: str) -> tuple[Path, str, str]:
    """Create a fixture repo with two commits; return (path, sha1, sha2)."""
    repo = fixtures_root / name
    repo.mkdir(parents=True)
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "app.py").write_text("print('v1')\n")
    _git(["add", "."], repo)
    _git(["commit", "-q", "-m", "v1"], repo)
    sha1 = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    (repo / "app.py").write_text("print('v2')\n")
    _git(["commit", "-q", "-am", "v2"], repo)
    sha2 = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    return repo, sha1, sha2


def _tv_with_source(session, fixture_ref, commit):
    return _tv_variant(session, task_prompt="inspect", source_fixture_ref=fixture_ref, source_commit=commit)


def test_git_fixture_is_cloned_and_source_commit_checked_out_exactly(tmp_path, fake_opencode):
    import os
    from aecc.execution import execute_run
    from aecc.models import RunState
    fixtures_root = Path(os.environ["AECC_FIXTURES_ROOT"])
    repo, sha1, sha2 = _make_git_fixture(fixtures_root, "subject")
    fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_with_source(s, "subject", sha1)  # older commit, not HEAD
        ws = _safe_workspace(tmp_path, "gitws")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="git-1", workspace=ws)
        assert run.state == RunState.COMPLETED, result.stderr
        # exact registered source presented to the model
        assert (ws / "app.py").read_text() == "print('v1')\n"
        assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ws), capture_output=True, text=True).stdout.strip() == sha1
        meta = json.loads(attempt.invocation_meta)
        assert meta["source"]["materialized"] == "git-clone"
        assert meta["source"]["materialized_commit"] == sha1
        assert run.source_commit == sha1 and run.source_fixture == "subject"
        # nothing AECC-specific inside the subject workspace
        assert not (ws / "task_prompt.txt").exists() and not (ws / ".source_commit").exists()
        # the fixture repo itself was not modified (still at v2)
        assert (repo / "app.py").read_text() == "print('v2')\n"
    engine.dispose()


def test_unknown_source_commit_is_refused_not_faked(tmp_path, fake_opencode):
    import os
    from aecc.execution import execute_run
    from aecc.models import RunState
    _make_git_fixture(Path(os.environ["AECC_FIXTURES_ROOT"]), "subject")
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_with_source(s, "subject", "0000000000000000000000000000000000000000")
        ws = _safe_workspace(tmp_path, "badsha")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="git-bad-1", workspace=ws)
        assert run.state == RunState.INFRASTRUCTURE_FAILURE
        assert "checkout of source_commit" in result.stderr
        assert not record.exists(), "harness must not run on unverified source"
    engine.dispose()


@pytest.mark.parametrize("ref,commit,expect", [
    ("missing-fixture", None, "fixture not found"),
    ("../etc", None, "parent traversal"),
    ("/etc/passwd", None, "absolute path"),
    ("~/.ssh/id_rsa", None, "absolute path"),
    ("sub\\evil", None, "illegal character"),
    (None, "abc123", "no source_fixture_ref"),
])
def test_fixture_refs_that_cannot_be_materialized_exactly_are_refused(tmp_path, fake_opencode, ref, commit, expect):
    from aecc.execution import execute_run
    from aecc.models import RunState
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_with_source(s, ref, commit)
        ws = _safe_workspace(tmp_path, "refuse")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key=f"fx-{ref}-{commit}", workspace=ws)
        assert run.state == RunState.INFRASTRUCTURE_FAILURE
        assert expect in result.stderr, result.stderr
        assert not record.exists()
        # no placeholder was fabricated into the workspace
        assert list(ws.iterdir()) == []
    engine.dispose()


def test_plain_directory_fixture_is_copied_and_digested(tmp_path, fake_opencode):
    import os
    from aecc.execution import execute_run, _tree_digest
    from aecc.models import RunState
    fx = Path(os.environ["AECC_FIXTURES_ROOT"]) / "plain"
    (fx / "pkg").mkdir(parents=True)
    (fx / "pkg" / "a.txt").write_text("A")
    (fx / "README").write_text("r")
    fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_with_source(s, "plain", None)
        ws = _safe_workspace(tmp_path, "plainws")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="plain-1", workspace=ws)
        assert run.state == RunState.COMPLETED, result.stderr
        assert (ws / "pkg" / "a.txt").read_text() == "A"
        meta = json.loads(attempt.invocation_meta)
        assert meta["source"]["materialized"] == "copy-tree"
        assert meta["source"]["tree_sha256"] == _tree_digest(fx)
    engine.dispose()


# ---------------------------------------------------------------------------
# Idempotency and provenance at the service layer
# ---------------------------------------------------------------------------

def test_idempotency_same_params_returns_existing_and_mismatch_refused(tmp_path):
    from aecc.execution import execute_run
    from aecc.models import Model
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        m2 = Model(model_key="other", provider="opencode", exact_identifier="opencode/other", is_active=True)
        s.add(m2); s.commit()
        ws = _safe_workspace(tmp_path, "idem")
        with mock.patch("aecc.execution._is_opencode_available", return_value=True):
            with mock.patch("aecc.execution._run_harness_process") as mrun:
                mrun.return_value = subprocess.CompletedProcess(args=["opencode"], returncode=0, stdout="ok", stderr="")
                run1, _, _ = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="k1", workspace=ws)
                run2, _, res2 = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="k1", workspace=ws)
                assert run2.id == run1.id and res2.error == "duplicate"
                assert mrun.call_count == 1
                with pytest.raises(ValueError, match="different parameters"):
                    execute_run(s, test_version_id=tv.id, model_id=m2.id, harness_id=h.id, idempotency_key="k1", workspace=ws)
    engine.dispose()


def test_demo_and_real_provenance_never_mix(tmp_path):
    from aecc.execution import execute_run
    from aecc.models import Harness
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        demo_h = Harness(harness_key="demo-opencode", config_snapshot=json.dumps({"adapter": "opencode"}), is_demo=True)
        s.add(demo_h); s.commit()
        ws = _safe_workspace(tmp_path, "mix")
        with pytest.raises(ValueError, match="provenance mismatch"):
            execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=demo_h.id, idempotency_key="mix-1", workspace=ws)
        # demo run against real test version is refused as well
        with pytest.raises(ValueError, match="provenance mismatch"):
            execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=demo_h.id, idempotency_key="mix-2", is_demo=True, workspace=ws)
        # auto-selection for a real run ignores the demo harness
        s.delete(h); s.commit()
        with pytest.raises(ValueError, match="no harness available"):
            execute_run(s, test_version_id=tv.id, model_id=m.id, idempotency_key="mix-3", workspace=ws)
    engine.dispose()


def test_adapter_registry_is_the_only_harness_specific_surface():
    """Future Codex/Claude/Kimi adapters plug in here; nothing else may know flags."""
    from aecc.execution import ADAPTERS, HarnessAdapter, resolve_adapter
    from aecc.models import Harness
    assert set(ADAPTERS) == {"opencode"}
    assert all(isinstance(a, HarnessAdapter) for a in ADAPTERS.values())
    assert resolve_adapter(Harness(harness_key="x", config_snapshot=json.dumps({"adapter": "codex"}))) is None
    assert resolve_adapter(Harness(harness_key="x", config_snapshot=json.dumps({"adapter": "opencode"}))).key == "opencode"


# ---------------------------------------------------------------------------
# R2 hardening: process group, fixtures, evidence root, git ancestry, env
# ---------------------------------------------------------------------------

def test_run_harness_subprocess_kills_process_group_on_timeout(tmp_path, fake_opencode):
    """A real timeout: the harness spawns a grandchild that must also die."""
    import time

    from aecc.execution import run_harness_subprocess
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    pid_file = tmp_path / "grandchild.pid"
    fake_opencode(exit_code=0, sleep_seconds=30, grandchild_pid_file=pid_file)
    ws = _safe_workspace(tmp_path, "ws_process_group")
    with factory() as s:
        h, m, tv = _make_harness_model_tv(s)
        result = run_harness_subprocess(tv, h, m, timeout_seconds=1, workspace=ws)
        assert result.timed_out is True
        assert result.error == "timeout"
    pid = None
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text().strip():
            pid = int(pid_file.read_text().strip())
            break
        time.sleep(0.05)
    assert pid is not None, "fake opencode never recorded a grandchild pid"

    def _still_running(pid: int) -> bool:
        try:
            with open(f"/proc/{pid}/stat") as fh:
                state = fh.read().rsplit(") ", 1)[1].split()[0]
        except FileNotFoundError:
            return False
        return state not in ("Z", "X", "x")

    alive = False
    for _ in range(100):
        if not _still_running(pid):
            alive = False
            break
        alive = True
        time.sleep(0.05)
    assert not alive, "grandchild process survived the process-group timeout kill"
    engine.dispose()


def test_harness_environment_is_allowlisted(monkeypatch):
    from pathlib import Path

    from aecc.execution import PERMISSION_PROFILES, _opencode_env
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-key-allowed")
    policy = PERMISSION_PROFILES["READ_ONLY_NO_SHELL"]
    env = _opencode_env(policy, Path("/tmp/ws"))
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert env.get("OPENROUTER_API_KEY") == "provider-key-allowed"
    assert "PATH" in env
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert "aecc-eval" in cfg["agent"]
    assert cfg["agent"]["aecc-eval"]["permission"]["bash"] == "deny"


def test_fixture_symlink_tree_is_refused(tmp_path, fake_opencode):
    import os

    from aecc.execution import execute_run
    from aecc.models import RunState
    fixtures_root = Path(os.environ["AECC_FIXTURES_ROOT"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be copied")
    fx = fixtures_root / "evil"
    fx.mkdir()
    (fx / "leak").symlink_to(outside, target_is_directory=True)
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_variant(s, task_prompt="t", source_fixture_ref="evil", source_commit=None)
        ws = _safe_workspace(tmp_path, "ws_symtree")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="sym-tree-1", workspace=ws)
        assert run.state == RunState.INFRASTRUCTURE_FAILURE
        assert "symlink" in result.stderr.lower()
    assert not record.exists(), "harness must not run on a symlinked fixture"
    engine.dispose()


def test_fixture_ref_that_is_a_symlink_is_refused(tmp_path, fake_opencode):
    import os

    from aecc.execution import execute_run
    from aecc.models import RunState
    fixtures_root = Path(os.environ["AECC_FIXTURES_ROOT"])
    outside = tmp_path / "outside2"
    outside.mkdir()
    (fixtures_root / "badlink").symlink_to(outside, target_is_directory=True)
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_variant(s, task_prompt="t", source_fixture_ref="badlink", source_commit=None)
        ws = _safe_workspace(tmp_path, "ws_symref")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key="sym-ref-1", workspace=ws)
        assert run.state == RunState.INFRASTRUCTURE_FAILURE
        assert "symlink" in result.stderr.lower()
    assert not record.exists()
    engine.dispose()


@pytest.mark.parametrize("bad_sha", ["abc", "ZZZZZZZ", "12345678g"])
def test_invalid_source_commit_is_refused(tmp_path, fake_opencode, bad_sha):
    import os

    from aecc.execution import execute_run
    from aecc.models import RunState
    fx = Path(os.environ["AECC_FIXTURES_ROOT"]) / "plain_sha"
    fx.mkdir()
    (fx / "a.txt").write_text("a")
    record = fake_opencode()
    engine = _engine(tmp_path)
    from aecc.db import create_session_factory
    factory = create_session_factory(engine)
    with factory() as s:
        h, m, tv = _tv_variant(s, task_prompt="t", source_fixture_ref="plain_sha", source_commit=bad_sha)
        ws = _safe_workspace(tmp_path, "ws_badsha")
        run, attempt, result = execute_run(s, test_version_id=tv.id, model_id=m.id, harness_id=h.id, idempotency_key=f"badsha-{bad_sha}", workspace=ws)
        assert run.state == RunState.INFRASTRUCTURE_FAILURE
        assert "7-40" in result.stderr
    assert not record.exists()
    engine.dispose()


def test_persist_evidence_refuses_symlinked_run_dir_escape(tmp_path):
    import os

    from aecc.execution import HarnessResult, _persist_evidence
    runs_root = Path(os.environ["AECC_RUNS_ROOT"])
    outside = tmp_path / "evidence_escape"
    outside.mkdir()
    (runs_root / "7").symlink_to(outside, target_is_directory=True)
    result = HarnessResult(exit_code=0, stdout="x", stderr="", elapsed_seconds=0.1, timed_out=False)
    location = _persist_evidence(7, 1, result, {"k": "v"})
    assert location is None
    assert not (outside / "stdout.txt").exists()


def test_git_file_ancestor_is_detected(tmp_path):
    """Linked worktrees/submodules use a `.git` *file*, not a directory."""
    from aecc.execution import _validate_workspace
    repo = tmp_path / "linked"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /somewhere/else\n")
    ws = repo / "sub"
    ws.mkdir()
    err = _validate_workspace(ws)
    assert err is not None and "git worktree" in err


def test_broken_git_symlink_ancestor_is_detected(tmp_path):
    from aecc.execution import _validate_workspace
    repo = tmp_path / "brokenlink"
    repo.mkdir()
    (repo / ".git").symlink_to(tmp_path / "does-not-exist")
    ws = repo / "sub"
    ws.mkdir()
    err = _validate_workspace(ws)
    assert err is not None and "git worktree" in err
