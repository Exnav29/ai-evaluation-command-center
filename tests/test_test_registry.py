"""Test Registry slice: reusable evaluation definitions with exact capability version preservation."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


def _make_client(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    db_file = tmp_path / "test_registry.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas
    apply_sqlite_pragmas(engine)
    from aecc.web import create_app
    from fastapi.testclient import TestClient
    app = create_app(engine=engine)
    client = TestClient(app, follow_redirects=False)
    client.engine = engine  # type: ignore
    client.db_file = db_file  # type: ignore
    return client, engine


@pytest.fixture()
def client(tmp_path):
    c, eng = _make_client(tmp_path)
    try:
        yield c
    finally:
        eng.dispose()


def _post_form(client, url, data: dict, follow=False):
    body = urllib.parse.urlencode(data)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return client.post(url, content=body, headers=headers, follow_redirects=follow)


def _factory(client):
    from aecc.db import create_session_factory
    return create_session_factory(client.engine)  # type: ignore


# ---------------------------------------------------------------------------
# Helpers to create capabilities and logical tests
# ---------------------------------------------------------------------------

def _create_capability(client, key, version, is_active=True):
    data = {"capability_key": key, "version": version}
    if is_active:
        data["is_active"] = "on"
    # need via web to go through validation
    resp = _post_form(client, "/operator/capabilities", data, follow=False)
    assert resp.status_code == 303, resp.text
    # retrieve id
    from aecc.models import Capability
    factory = _factory(client)
    with factory() as s:
        cap = s.scalar(select(Capability).where(Capability.capability_key == key, Capability.version == version))
        return cap.id if cap else None


def _create_logical_test(client, key="test-key", name="Test Name", description="desc"):
    resp = _post_form(client, "/operator/tests", {"key": key, "name": name, "description": description}, follow=False)
    assert resp.status_code == 303, resp.text
    loc = resp.headers.get("location") or resp.headers.get("Location")
    assert loc
    return int(loc.rstrip("/").split("/")[-1])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_registry_list_create_detail(client):
    # empty list
    resp = client.get("/operator/tests")
    assert resp.status_code == 200
    assert "Test Registry" in resp.text
    assert "No logical tests" in resp.text
    # new form
    assert client.get("/operator/tests/new").status_code == 200
    assert "New logical test" in client.get("/operator/tests/new").text
    # create
    tid = _create_logical_test(client, key="my-test", name="My Test")
    # list shows it
    html = client.get("/operator/tests").text
    assert "my-test" in html
    assert "My Test" in html
    # detail
    detail = client.get(f"/operator/tests/{tid}")
    assert detail.status_code == 200
    assert "my-test" in detail.text
    assert "My Test" in detail.text


def test_register_immutable_v1(client):
    cap_id = _create_capability(client, "cap.test", "v1")
    tid = _create_logical_test(client, key="t1", name="T1")
    resp = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap_id),
        "task_prompt": "do thing",
        "acceptance_criteria": "accept",
        "rubric_id": "rub",
        "rubric_version": "1.0",
        "permission_profile": "READ_ONLY_NO_SHELL",
    }, follow=False)
    assert resp.status_code == 303
    assert resp.headers.get("location") or resp.headers.get("Location")
    # detail shows v1 current
    html = client.get(f"/operator/tests/{tid}").text
    assert "v1" in html
    assert "current" in html.lower()
    assert "cap.test" in html
    assert "v1" in html  # capability version also


def test_register_v2_preserves_v1_and_supersedes(client):
    cap_id = _create_capability(client, "cap.preserve", "v1")
    tid = _create_logical_test(client, key="preserve-t", name="Preserve")
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap_id),
        "task_prompt": "original",
        "acceptance_criteria": "accept",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "READ_ONLY_NO_SHELL",
    }, follow=False)
    # second version clarified
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap_id),
        "task_prompt": "clarified",
        "acceptance_criteria": "accept",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "READ_ONLY_NO_SHELL",
    }, follow=False)
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        vs = list(s.scalars(select(TestVersion).where(TestVersion.logical_test_id == tid).order_by(TestVersion.version_number)).all())
        assert len(vs) == 2
        assert vs[0].task_prompt == "original"
        assert vs[1].task_prompt == "clarified"
        assert vs[1].supersedes_version_id == vs[0].id
        assert vs[0].definition_hash != vs[1].definition_hash
    html = client.get(f"/operator/tests/{tid}").text
    assert html.count("v1") >= 1 and html.count("v2") >= 1
    # successor link in version detail
    assert client.get(f"/operator/tests/versions/{vs[0].id}").text.count("Superseded by") >= 1
    assert f"v{vs[0].version_number}" in client.get(f"/operator/tests/versions/{vs[1].id}").text


def test_exact_capability_version_preservation(client):
    c1 = _create_capability(client, "cap.versioned", "v1")
    c2 = _create_capability(client, "cap.versioned", "v2")
    tid = _create_logical_test(client, key="exact-v", name="Exact")
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(c1),
        "task_prompt": "p",
        "acceptance_criteria": "a",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "READ_ONLY_NO_SHELL",
    }, follow=False)
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        v1 = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid))
        assert v1.capability_key == "cap.versioned"
        assert v1.capability_version == "v1"
    # second version using v2
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(c2),
        "task_prompt": "p2",
        "acceptance_criteria": "a",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "READ_ONLY_NO_SHELL",
    }, follow=False)
    with factory() as s:
        vs = list(s.scalars(select(TestVersion).where(TestVersion.logical_test_id == tid).order_by(TestVersion.version_number)).all())
        assert vs[1].capability_version == "v2"
        # html shows both versions distinct
    html = client.get(f"/operator/tests/{tid}").text
    assert "cap.versioned v1" in html
    assert "cap.versioned v2" in html
    # version detail shows exact
    assert "cap.versioned" in client.get(f"/operator/tests/versions/{vs[0].id}").text
    assert "v1" in client.get(f"/operator/tests/versions/{vs[0].id}").text
    assert "v2" in client.get(f"/operator/tests/versions/{vs[1].id}").text


def test_same_capability_key_unambiguous_two_versions(client):
    # ensure two capabilities with same key different versions are offered as distinct options
    c1 = _create_capability(client, "cap.same", "v1")
    c2 = _create_capability(client, "cap.same", "v2")
    tid = _create_logical_test(client, key="same-t", name="Same")
    html_form = client.get(f"/operator/tests/{tid}/versions/new").text
    # both options present with distinct ids
    assert f'value="{c1}"' in html_form
    assert f'value="{c2}"' in html_form
    assert "cap.same v1" in html_form
    assert "cap.same v2" in html_form
    # register each and verify distinct preservation
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(c1), "task_prompt": "p1", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(c2), "task_prompt": "p2", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        vs = list(s.scalars(select(TestVersion).where(TestVersion.logical_test_id == tid).order_by(TestVersion.version_number)).all())
        assert vs[0].capability_version == "v1"
        assert vs[1].capability_version == "v2"
        assert vs[0].capability_key == vs[1].capability_key == "cap.same"
        assert vs[0].definition_hash != vs[1].definition_hash  # version affects hash


def test_inactive_excluded_from_new_registration(client):
    active = _create_capability(client, "cap.active2", "v1", is_active=True)
    inactive_id = _create_capability(client, "cap.inactive2", "v1", is_active=True)
    # deactivate
    from aecc.models import Capability
    factory = _factory(client)
    with factory() as s:
        cap = s.get(Capability, inactive_id)
        assert cap is not None
    # deactivate via edit (omit is_active)
    body = urllib.parse.urlencode({"capability_key": "cap.inactive2", "version": "v1"})
    client.post(f"/operator/capabilities/{inactive_id}/edit", content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=True)
    tid = _create_logical_test(client, key="inactive-t", name="Inactive")
    html_form = client.get(f"/operator/tests/{tid}/versions/new").text
    assert "cap.active2" in html_form
    assert "cap.inactive2" not in html_form
    # attempt to register with inactive should 400
    resp = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(inactive_id),
        "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    assert resp.status_code == 400
    assert "not active" in resp.text.lower()


def test_historical_inactive_remains_visible(client):
    active = _create_capability(client, "cap.hist", "v1", is_active=True)
    tid = _create_logical_test(client, key="hist-t", name="Hist")
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(active), "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    # deactivate
    body = urllib.parse.urlencode({"capability_key": "cap.hist", "version": "v1"})
    client.post(f"/operator/capabilities/{active}/edit", content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=True)
    # still visible in list and detail
    html_list = client.get(f"/operator/tests/{tid}").text
    assert "cap.hist" in html_list
    assert "v1" in html_list
    # form no longer offers it but history still there (select options exclude inactive, note may still mention previous)
    html_form = client.get(f"/operator/tests/{tid}/versions/new").text
    assert f'value="{active}"' not in html_form
    # option for inactive should not be present
    assert "cap.hist" not in html_form.split('<select')[1].split('</select>')[0] if '<select' in html_form else True
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        v = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid))
        assert v is not None
        detail = client.get(f"/operator/tests/versions/{v.id}")
        assert detail.status_code == 200
        assert "cap.hist" in detail.text
        assert "inactive" in detail.text.lower()


def test_definition_hash_consistency_and_version_affects_hash(client):
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    cap1 = _create_capability(client, "cap.hash", "v1")
    cap2 = _create_capability(client, "cap.hash", "v2")
    tid = _create_logical_test(client, key="hash-t", name="Hash")
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap1),
        "task_prompt": "same task",
        "acceptance_criteria": "same accept",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "P",
        "timeout_seconds": "300",
        "retry_policy": '{"max_attempts": 2}',
        "expected_artifacts": '["out.txt"]',
        "source_fixture_ref": "fix",
        "source_commit": "abc",
    }, follow=False)
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        v1 = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid, TestVersion.version_number == 1))
        assert v1 is not None
        # recompute hash and compare
        payload = build_definition_payload(
            task_prompt="same task",
            acceptance_criteria="same accept",
            rubric_id="r",
            rubric_version="1",
            source_fixture_ref="fix",
            source_commit="abc",
            permission_profile="P",
            retry_policy={"max_attempts": 2},
            timeout_seconds=300,
            expected_artifacts=["out.txt"],
            capability_key="cap.hash",
            capability_version="v1",
        )
        assert canonical_definition_hash(payload) == v1.definition_hash
        # same payload with different capability version must differ
        payload2 = build_definition_payload(
            task_prompt="same task",
            acceptance_criteria="same accept",
            rubric_id="r",
            rubric_version="1",
            source_fixture_ref="fix",
            source_commit="abc",
            permission_profile="P",
            retry_policy={"max_attempts": 2},
            timeout_seconds=300,
            expected_artifacts=["out.txt"],
            capability_key="cap.hash",
            capability_version="v2",
        )
        assert canonical_definition_hash(payload2) != v1.definition_hash
    # register second version with same fields but different capability version → different hash despite same task
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap2),
        "task_prompt": "same task",
        "acceptance_criteria": "same accept",
        "rubric_id": "r",
        "rubric_version": "1",
        "permission_profile": "P",
        "timeout_seconds": "300",
        "retry_policy": '{"max_attempts": 2}',
        "expected_artifacts": '["out.txt"]',
        "source_fixture_ref": "fix",
        "source_commit": "abc",
    }, follow=False)
    with factory() as s:
        v2 = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid, TestVersion.version_number == 2))
        assert v2.definition_hash != v1.definition_hash
        assert v2.capability_version == "v2"


def test_form_validation_and_duplicate_key(client):
    # missing fields
    resp = _post_form(client, "/operator/tests", {"key": "", "name": ""}, follow=False)
    assert resp.status_code == 400
    # duplicate key
    _create_logical_test(client, key="dup-key", name="First")
    resp2 = _post_form(client, "/operator/tests", {"key": "dup-key", "name": "Second"}, follow=False)
    assert resp2.status_code == 400
    assert "already exists" in resp2.text
    # version required fields
    cap = _create_capability(client, "cap.valid", "v1")
    tid = _create_logical_test(client, key="valid-t", name="Valid")
    resp3 = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap),
        "task_prompt": "",
        "acceptance_criteria": "",
        "rubric_id": "",
        "rubric_version": "",
        "permission_profile": "",
    }, follow=False)
    assert resp3.status_code == 400
    # timeout validation
    resp4 = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap),
        "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P",
        "timeout_seconds": "not-an-int"
    }, follow=False)
    assert resp4.status_code == 400
    assert "Timeout" in resp4.text
    # json validation
    resp5 = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap),
        "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P",
        "retry_policy": "not-json"
    }, follow=False)
    assert resp5.status_code == 400
    assert "Retry policy" in resp5.text


def test_route_status_codes(client):
    assert client.get("/operator/tests").status_code == 200
    assert client.get("/operator/tests/new").status_code == 200
    assert client.get("/operator/tests/999999").status_code == 404
    assert client.get("/operator/tests/versions/999999").status_code == 404
    cap = _create_capability(client, "cap.route", "v1")
    tid = _create_logical_test(client, key="route-t", name="Route")
    assert client.get(f"/operator/tests/{tid}").status_code == 200
    assert client.get(f"/operator/tests/{tid}/versions/new").status_code == 200
    assert client.get("/operator/tests/999999/versions/new").status_code == 404
    # POST unknown logical test
    resp = _post_form(client, "/operator/tests/999999/versions", {
        "capability_id": str(cap), "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    assert resp.status_code == 404
    # successful create is 303
    resp2 = _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap), "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    assert resp2.status_code == 303
    # GET version detail 200
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        v = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid))
        assert client.get(f"/operator/tests/versions/{v.id}").status_code == 200


def test_immutability_still_enforced(client):
    cap = _create_capability(client, "cap.immut", "v1")
    tid = _create_logical_test(client, key="immut-t", name="Immut")
    _post_form(client, f"/operator/tests/{tid}/versions", {
        "capability_id": str(cap), "task_prompt": "p", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"
    }, follow=False)
    from aecc.models import TestVersion
    factory = _factory(client)
    with factory() as s:
        v = s.scalar(select(TestVersion).where(TestVersion.logical_test_id == tid))
        vid = v.id
    # try via ORM
    with factory() as s:
        v2 = s.get(TestVersion, vid)
        v2.task_prompt = "mutated"
        with pytest.raises(sa.exc.DBAPIError):
            s.commit()
        s.rollback()
    # via raw SQL
    with client.engine.connect() as conn:  # type: ignore
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with conn.begin():
                conn.execute(text("UPDATE test_versions SET task_prompt='mutated' WHERE id=:i"), {"i": vid})
    with client.engine.connect() as conn:  # type: ignore
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with conn.begin():
                conn.execute(text("DELETE FROM test_versions WHERE id=:i"), {"i": vid})


def test_navigation_and_latest_obvious(client):
    cap = _create_capability(client, "cap.nav", "v1")
    tid = _create_logical_test(client, key="nav-t", name="Nav")
    html = client.get("/operator").text
    assert 'href="/operator/tests"' in html
    assert 'href="/operator/capabilities"' in html
    html2 = client.get("/operator/tests").text
    assert 'href="/operator/tests/new"' in html2
    # register versions and check latest obvious
    _post_form(client, f"/operator/tests/{tid}/versions", {"capability_id": str(cap), "task_prompt": "p1", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"}, follow=False)
    _post_form(client, f"/operator/tests/{tid}/versions", {"capability_id": str(cap), "task_prompt": "p2", "acceptance_criteria": "a", "rubric_id": "r", "rubric_version": "1", "permission_profile": "P"}, follow=False)
    html_detail = client.get(f"/operator/tests/{tid}").text
    assert "current" in html_detail.lower()
    assert "history" in html_detail.lower()
    # latest should be v2
    assert 'data-version-number="2"' in html_detail
    assert html_detail.count("badge-pass") >= 1


def test_migration_leaves_historical_capability_version_null(tmp_path):
    """Historical rows created at 0002 must remain NULL even when multiple matching capabilities exist."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from aecc.db import create_engine_for_path
    from aecc.hashing import build_definition_payload, canonical_definition_hash

    db_file = tmp_path / "migration_null.sqlite"
    cfg = _alembic_config(db_file)
    # start at 0002
    command.upgrade(cfg, "0002_registry_foundation")

    engine = create_engine_for_path(db_file)
    # insert historical logical_test + test_version with only capability_key (no version)
    # also insert two capabilities with same key different versions to prove no inference
    with engine.connect() as conn:
        # logical_test
        conn.execute(text("INSERT INTO logical_tests (key, name, description, created_at) VALUES ('legacy-key', 'Legacy', 'hist', CURRENT_TIMESTAMP)"))
        lt_id = conn.execute(text("SELECT id FROM logical_tests WHERE key='legacy-key'")).scalar()
        # capabilities
        conn.execute(text("INSERT INTO capabilities (capability_key, version, definition, description, created_at, is_active) VALUES ('legacy.test', 'v1', 'def', 'desc', CURRENT_TIMESTAMP, 1)"))
        conn.execute(text("INSERT INTO capabilities (capability_key, version, definition, description, created_at, is_active) VALUES ('legacy.test', 'v2', 'def', 'desc', CURRENT_TIMESTAMP, 1)"))
        # test_version at 0002 schema: no capability_version column yet
        payload = build_definition_payload(
            task_prompt="hist task",
            acceptance_criteria="hist accept",
            rubric_id="r",
            rubric_version="1",
            permission_profile="READ_ONLY_NO_SHELL",
            capability_key="legacy.test",
        )
        h = canonical_definition_hash(payload)
        conn.execute(text("""
            INSERT INTO test_versions (logical_test_id, version_number, task_prompt, capability_key, acceptance_criteria, rubric_id, rubric_version, permission_profile, created_at, registered_at, definition_hash)
            VALUES (:lt, 1, 'hist task', 'legacy.test', 'hist accept', 'r', '1', 'READ_ONLY_NO_SHELL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :h)
        """), {"lt": lt_id, "h": h})
        conn.commit()
        tv_id = conn.execute(text("SELECT id FROM test_versions WHERE logical_test_id=:lt"), {"lt": lt_id}).scalar()
        # verify pre-migration: capability_version column does not exist yet, so not checking
        pre_hash = conn.execute(text("SELECT definition_hash FROM test_versions WHERE id=:i"), {"i": tv_id}).scalar()
        assert pre_hash == h

    engine.dispose()
    # now upgrade to head (0003)
    command.upgrade(cfg, "head")

    engine2 = create_engine_for_path(db_file)
    try:
        with engine2.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(test_versions)")).fetchall()}
            assert "capability_version" in cols
            # historical row must still be NULL, not inferred to v1 or v2
            cap_ver = conn.execute(text("SELECT capability_version FROM test_versions WHERE id=:i"), {"i": tv_id}).scalar()
            assert cap_ver is None, f"historical capability_version must remain NULL, got {cap_ver!r} even though multiple matching capabilities exist"
            # hash must not be rewritten
            post_hash = conn.execute(text("SELECT definition_hash FROM test_versions WHERE id=:i"), {"i": tv_id}).scalar()
            assert post_hash == pre_hash == h
            # capabilities still both present
            cnt = conn.execute(text("SELECT COUNT(*) FROM capabilities WHERE capability_key='legacy.test'")).scalar()
            assert cnt == 2
            # new registration after migration must require exact version (tested elsewhere) – smoke check that column is nullable but new rows need version
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() in ("0003_test_registry_capability_version", "0004_execution_and_demo", "0005_provenance_relabel_guard")
    finally:
        engine2.dispose()
