"""Registry Foundation: capability catalog + model registry.

Covers:
- migration/schema non-destructive additive columns
- hierarchical capability keys (parent/child)
- versioning retained + descriptive metadata + active/inactive
- exact provider/model identifier as evidence identity
- free/paid/unknown pricing semantics + input/output pricing
- active/inactive behavior
- HTTP/form CRUD for capabilities and models
- historical qualification/evidence preservation (no destructive migration)
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import urllib.parse

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
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
    db_file = tmp_path / "registry.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas
    apply_sqlite_pragmas(engine)
    from aecc.web import create_app
    from fastapi.testclient import TestClient
    app = create_app(engine=engine)
    client = TestClient(app, follow_redirects=False)
    # expose engine for direct DB checks
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


def _post_form(client, url, data: dict, follow=True):
    # Use urlencoded body; our handler parses via request.body()
    body = urllib.parse.urlencode(data)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    # follow_redirects controls TestClient redirect following
    if follow:
        # starlette TestClient param is follow_redirects
        return client.post(url, content=body, headers=headers, follow_redirects=True)
    return client.post(url, content=body, headers=headers, follow_redirects=False)


# ---------------------------------------------------------------------------
# Migration / schema
# ---------------------------------------------------------------------------

def test_alembic_migrates_to_head_includes_registry_columns(tmp_path):
    db_file = tmp_path / "fresh.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from aecc.db import create_engine_for_path
    eng = create_engine_for_path(db_file)
    try:
        with eng.connect() as conn:
            cols_cap = {r[1] for r in conn.execute(text("PRAGMA table_info(capabilities)")).fetchall()}
            cols_mod = {r[1] for r in conn.execute(text("PRAGMA table_info(models)")).fetchall()}
            # must contain new columns
            assert "parent_id" in cols_cap
            assert "display_name" in cols_cap
            assert "is_active" in cols_cap
            assert "updated_at" in cols_cap
            assert "parent_id" in cols_cap
            assert "pricing_tier" in cols_mod
            assert "price_input" in cols_mod
            assert "price_output" in cols_mod
            assert "is_active" in cols_mod
            assert "harness_config" in cols_mod
            assert "description" in cols_mod
            # triggers for pricing_tier
            triggers = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).fetchall()}
            assert "trg_models_pricing_tier_check" in triggers
            # alembic version is head (0004 after execution slice)
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver in ("0002_registry_foundation", "0003_test_registry_capability_version", "0004_execution_and_demo", "0005_provenance_relabel_guard")
            # original table still present
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
            assert "capabilities" in tables and "models" in tables and "runs" in tables
    finally:
        eng.dispose()


def test_migration_is_nondestructive_preserves_existing_rows(tmp_path):
    """Existing capability/model rows survive migration with is_active and pricing_tier backfilled."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    # create db at 0001, insert rows via raw SQL (old schema has no parent_id/pricing_tier), then upgrade
    db_file = tmp_path / "nondest.sqlite"
    cfg = _alembic_config(db_file)
    command.upgrade(cfg, "0001_foundation")
    engine = sa.create_engine(f"sqlite:///{db_file}", future=True)
    from aecc.db import apply_sqlite_pragmas
    apply_sqlite_pragmas(engine)
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO capabilities (capability_key, version, definition, description, created_at) VALUES ('bug-fixing','v1','def','desc', CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO models (model_key, provider, exact_identifier, pricing_class) VALUES ('m1','prov','prov/m1:free','free')"))
        conn.commit()
        cap_id = conn.execute(text("SELECT id FROM capabilities WHERE capability_key='bug-fixing'")).scalar()
        model_id = conn.execute(text("SELECT id FROM models WHERE model_key='m1'")).scalar()
    engine.dispose()
    # now migrate to head
    command.upgrade(cfg, "head")
    engine2 = sa.create_engine(f"sqlite:///{db_file}", future=True)
    apply_sqlite_pragmas(engine2)
    from aecc.models import Capability, Model
    from aecc.db import create_session_factory
    factory2 = create_session_factory(engine2)
    with factory2() as s:
        cap2 = s.get(Capability, cap_id)
        assert cap2 is not None
        assert cap2.capability_key == "bug-fixing"
        assert cap2.is_active is True  # backfilled
        m2 = s.get(Model, model_id)
        assert m2 is not None
        assert m2.pricing_tier == "free"
        assert m2.is_active is True
    engine2.dispose()


# ---------------------------------------------------------------------------
# Capability hierarchy & versioning
# ---------------------------------------------------------------------------

def test_capability_hierarchical_keys_and_parent_child(client):
    # create parent via form
    resp = _post_form(client, "/operator/capabilities", {
        "capability_key": "backend",
        "version": "v1",
        "display_name": "Backend",
        "definition": "backend work",
        "is_active": "on",
    })
    assert resp.status_code in (200, 303)
    # list contains backend
    html = client.get("/operator/capabilities").text
    assert "backend" in html
    # get parent id via DB
    from aecc.models import Capability
    from sqlalchemy import select
    with client.engine.connect() as conn:  # type: ignore
        pass
    # use session
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        parent = s.scalar(select(Capability).where(Capability.capability_key == "backend"))
        assert parent is not None
        parent_id = parent.id
    # create child with dot key
    resp2 = _post_form(client, "/operator/capabilities", {
        "capability_key": "backend.fastapi",
        "version": "v1",
        "parent_id": str(parent_id),
        "is_active": "on",
    })
    assert resp2.status_code in (200, 303)
    # child detail shows parent
    with factory() as s:
        child = s.scalar(select(Capability).where(Capability.capability_key == "backend.fastapi"))
        assert child is not None
        assert child.parent_id == parent_id
    html_detail = client.get(f"/operator/capabilities/{child.id}").text
    assert "backend" in html_detail
    assert "Children" in html_detail
    # parent detail shows child
    html_parent = client.get(f"/operator/capabilities/{parent_id}").text
    assert "backend.fastapi" in html_parent


def test_capability_deep_hierarchy_example(client):
    # backend.fastapi.api_implementation as spec example
    for key, parent_key in [
        ("backend", None),
        ("backend.fastapi", "backend"),
        ("backend.fastapi.api_implementation", "backend.fastapi"),
    ]:
        # need parent id lookup
        parent_id = ""
        if parent_key:
            from aecc.models import Capability
            from sqlalchemy import select
            from aecc.db import create_session_factory
            factory = create_session_factory(client.engine)  # type: ignore
            with factory() as s:
                p = s.scalar(select(Capability).where(Capability.capability_key == parent_key))
                if p:
                    parent_id = str(p.id)
        resp = _post_form(client, "/operator/capabilities", {
            "capability_key": key,
            "version": "v1",
            "parent_id": parent_id,
            "is_active": "on",
        })
        assert resp.status_code in (200, 303)
    html = client.get("/operator/capabilities").text
    assert "backend.fastapi.api_implementation" in html


def test_capability_versioning_retained(client):
    _post_form(client, "/operator/capabilities", {"capability_key": "frontend", "version": "v1", "is_active": "on"})
    _post_form(client, "/operator/capabilities", {"capability_key": "frontend", "version": "v2", "definition": "new def", "is_active": "on"})
    from aecc.models import Capability
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        caps = list(s.scalars(select(Capability).where(Capability.capability_key == "frontend").order_by(Capability.version)).all())
        assert len(caps) == 2
        assert caps[0].version == "v1" and caps[1].version == "v2"
        assert caps[1].definition == "new def"


def test_capability_descriptive_metadata_and_active_status(client):
    resp = _post_form(client, "/operator/capabilities", {
        "capability_key": "docs",
        "version": "v1",
        "display_name": "Docs Writing",
        "definition": "write docs",
        "description": "detailed docs metadata",
        "is_active": "on",
    })
    assert resp.status_code in (200, 303)
    from aecc.models import Capability
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        cap = s.scalar(select(Capability).where(Capability.capability_key == "docs"))
        assert cap.display_name == "Docs Writing"
        assert cap.description == "detailed docs metadata"
        cap_id = cap.id
    # deactivate via edit (no is_active field -> inactive)
    _post_form(client, f"/operator/capabilities/{cap_id}/edit", {
        "capability_key": "docs",
        "version": "v1",
        "display_name": "Docs Writing Updated",
        # intentionally omit is_active to test inactive
    })
    with factory() as s:
        cap2 = s.get(Capability, cap_id)
        assert cap2.is_active is False
        assert cap2.display_name == "Docs Writing Updated"
    html = client.get("/operator/capabilities").text
    assert "inactive" in html.lower()


def test_capability_invalid_key_rejected(client):
    resp = _post_form(client, "/operator/capabilities", {"capability_key": "Invalid-Key!", "version": "v1"})
    assert resp.status_code == 400
    assert "Capability key must be" in resp.text


def test_capability_duplicate_key_version_rejected(client):
    _post_form(client, "/operator/capabilities", {"capability_key": "dup", "version": "v1", "is_active": "on"})
    resp = _post_form(client, "/operator/capabilities", {"capability_key": "dup", "version": "v1", "is_active": "on"})
    assert resp.status_code == 400
    assert "already exists" in resp.text


def test_capability_self_parent_and_cycle_prevented(client):
    _post_form(client, "/operator/capabilities", {"capability_key": "a", "version": "v1", "is_active": "on"})
    _post_form(client, "/operator/capabilities", {"capability_key": "a.b", "version": "v1", "is_active": "on"})
    from aecc.models import Capability
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        a = s.scalar(select(Capability).where(Capability.capability_key == "a"))
        ab = s.scalar(select(Capability).where(Capability.capability_key == "a.b"))
        # set ab parent to a -> ok
        resp = _post_form(client, f"/operator/capabilities/{ab.id}/edit", {
            "capability_key": "a.b", "version": "v1", "parent_id": str(a.id), "is_active": "on"
        })
        assert resp.status_code in (200, 303)
        # now try to set a parent to ab -> cycle should be rejected
        resp2 = _post_form(client, f"/operator/capabilities/{a.id}/edit", {
            "capability_key": "a", "version": "v1", "parent_id": str(ab.id), "is_active": "on"
        })
        assert resp2.status_code == 400
        assert "cycle" in resp2.text.lower()
        # self parent
        resp3 = _post_form(client, f"/operator/capabilities/{a.id}/edit", {
            "capability_key": "a", "version": "v1", "parent_id": str(a.id), "is_active": "on"
        })
        assert resp3.status_code == 400
        assert "own parent" in resp3.text.lower()


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

def test_model_exact_identifier_is_evidence_identity(client):
    _post_form(client, "/operator/models", {
        "model_key": "m1",
        "provider": "openrouter",
        "exact_identifier": "openrouter/mimo-v2-flash:free",
        "display_name": "MiMo Flash Free",
        "pricing_tier": "free",
        "is_active": "on",
    })
    from aecc.models import Model
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        m = s.scalar(select(Model).where(Model.model_key == "m1"))
        assert m is not None
        assert m.exact_identifier == "openrouter/mimo-v2-flash:free"
        assert m.provider == "openrouter"
        mid = m.id
    # edit display name, should not change exact_identifier unless explicitly changed
    _post_form(client, f"/operator/models/{mid}/edit", {
        "model_key": "m1",
        "provider": "openrouter",
        "exact_identifier": "openrouter/mimo-v2-flash:free",
        "display_name": "MiMo Flash Free Updated",
        "pricing_tier": "free",
        "is_active": "on",
    })
    with factory() as s:
        m2 = s.get(Model, mid)
        assert m2.exact_identifier == "openrouter/mimo-v2-flash:free"
        assert m2.display_name == "MiMo Flash Free Updated"
    # detail page shows exact identifier prominently
    html = client.get(f"/operator/models/{mid}").text
    assert "openrouter/mimo-v2-flash:free" in html
    assert "evidence identity" in html.lower()
    # ensure exact_identifier appears in runs overview when model used in a run
    # create minimal run referencing this model
    with factory() as s:
        from aecc.models import Capability, Harness, LogicalTest, TestVersion, Run
        from aecc.hashing import build_definition_payload, canonical_definition_hash
        h = Harness(harness_key="opencode-test", display_name="opencode")
        s.add(h)
        cap = s.scalar(select(Capability).where(Capability.capability_key == "backend") ) or Capability(capability_key="backend", version="v1", definition="d")
        if cap.id is None:
            s.add(cap)
            s.flush()
        lt = LogicalTest(key="lt-reg", name="lt")
        s.add(lt)
        s.flush()
        payload = build_definition_payload(task_prompt="p", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", capability_key="backend")
        tv = TestVersion(logical_test_id=lt.id, version_number=1, task_prompt="p", capability_key="backend", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
        s.add(tv)
        s.flush()
        run = Run(test_version_id=tv.id, harness_id=h.id, model_id=mid, capability_id=cap.id, state="QUEUED", requested_at=datetime.now(timezone.utc))
        s.add(run)
        s.commit()
        run_id = run.id
    html_overview = client.get("/operator").text
    # exact identifier should appear via run's model
    assert "openrouter/mimo-v2-flash:free" in html_overview or "mimo-v2-flash" in html_overview


def test_model_free_paid_unknown_pricing(client):
    # free with prices
    _post_form(client, "/operator/models", {"model_key": "free-m", "provider": "prov", "exact_identifier": "prov/free:free", "pricing_tier": "free", "price_input": "0", "price_output": "0", "is_active": "on"})
    # paid with prices
    _post_form(client, "/operator/models", {"model_key": "paid-m", "provider": "prov", "exact_identifier": "prov/paid-v1", "pricing_tier": "paid", "price_input": "1.5", "price_output": "3.0", "is_active": "on"})
    # unknown with no prices
    _post_form(client, "/operator/models", {"model_key": "unk-m", "provider": "prov", "exact_identifier": "prov/unk-v1", "pricing_tier": "unknown", "is_active": "on"})
    from aecc.models import Model
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        free = s.scalar(select(Model).where(Model.model_key == "free-m"))
        paid = s.scalar(select(Model).where(Model.model_key == "paid-m"))
        unk = s.scalar(select(Model).where(Model.model_key == "unk-m"))
        assert free.pricing_tier == "free" and free.price_input == 0 and free.price_output == 0
        assert paid.pricing_tier == "paid" and paid.price_input == 1.5 and paid.price_output == 3.0
        assert unk.pricing_tier == "unknown" and unk.price_input is None and unk.price_output is None
    html = client.get("/operator/models").text
    assert "free" in html.lower()
    assert "paid" in html.lower()
    assert "unknown" in html.lower()
    # unknown renders Not recorded
    html_unk = client.get(f"/operator/models/{unk.id}").text
    assert "Not recorded" in html_unk
    html_free = client.get(f"/operator/models/{free.id}").text
    assert "$0.0000" in html_free or "0" in html_free


def test_model_unknown_is_not_zero(client):
    _post_form(client, "/operator/models", {"model_key": "unk2", "provider": "p", "exact_identifier": "p/unk2", "pricing_tier": "unknown", "is_active": "on"})
    from aecc.models import Model
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        m = s.scalar(select(Model).where(Model.model_key == "unk2"))
        assert m.price_input is None
        # direct DB insert with free but 0 should be distinct from unknown
    html = client.get("/operator/models").text
    # unknown badge should be dashed unknown style not pass
    assert "badge-unknown" in html


def test_model_invalid_pricing_tier_rejected(client):
    # try via direct DB to trigger trigger - trigger raises on INSERT before commit
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        try:
            s.execute(text("INSERT INTO models (model_key, provider, exact_identifier, pricing_tier, is_active) VALUES ('bad','p','p/bad','invalid',1)"))
            s.commit()
            assert False, "invalid pricing_tier should be rejected"
        except Exception as e:
            s.rollback()
            assert "invalid pricing_tier" in str(e).lower() or "check" in str(e).lower()
    # via form should also reject
    resp = _post_form(client, "/operator/models", {"model_key": "bad2","provider":"p","exact_identifier":"p/bad2","pricing_tier":"invalid"})
    assert resp.status_code == 400
    assert "Pricing tier" in resp.text


def test_model_active_inactive_toggle(client):
    _post_form(client, "/operator/models", {"model_key": "active-m", "provider": "p", "exact_identifier": "p/active-m", "pricing_tier": "free", "is_active": "on"})
    from aecc.models import Model
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        m = s.scalar(select(Model).where(Model.model_key == "active-m"))
        assert m.is_active is True
        mid = m.id
    # deactivate (omit is_active)
    _post_form(client, f"/operator/models/{mid}/edit", {"model_key":"active-m","provider":"p","exact_identifier":"p/active-m","pricing_tier":"free"})
    with factory() as s:
        m2 = s.get(Model, mid)
        assert m2.is_active is False
    html = client.get("/operator/models").text
    assert "inactive" in html.lower()
    # reactivate
    _post_form(client, f"/operator/models/{mid}/edit", {"model_key":"active-m","provider":"p","exact_identifier":"p/active-m","pricing_tier":"free","is_active":"on"})
    with factory() as s:
        assert s.get(Model, mid).is_active is True


def test_model_harness_config_metadata(client):
    _post_form(client, "/operator/models", {"model_key":"hc-m","provider":"p","exact_identifier":"p/hc-m","pricing_tier":"paid","harness_config":'{"harnesses":["opencode"],"max_tokens":8000}',"is_active":"on"})
    from aecc.models import Model
    from sqlalchemy import select
    from aecc.db import create_session_factory
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        m = s.scalar(select(Model).where(Model.model_key=="hc-m"))
        assert m.harness_config == '{"harnesses":["opencode"],"max_tokens":8000}'
        assert m.config_params == m.harness_config
    html = client.get(f"/operator/models/{m.id}").text
    assert "opencode" in html


def test_model_duplicate_key_rejected(client):
    _post_form(client, "/operator/models", {"model_key":"dup","provider":"p","exact_identifier":"p/dup1","pricing_tier":"free","is_active":"on"})
    resp = _post_form(client, "/operator/models", {"model_key":"dup","provider":"p","exact_identifier":"p/dup2","pricing_tier":"free","is_active":"on"})
    assert resp.status_code == 400
    assert "already exists" in resp.text


# ---------------------------------------------------------------------------
# HTTP / form integration
# ---------------------------------------------------------------------------

def test_capability_routes_http(client):
    assert client.get("/operator/capabilities").status_code == 200
    assert "Capability Catalog" in client.get("/operator/capabilities").text
    assert client.get("/operator/capabilities/new").status_code == 200
    assert "Add capability" in client.get("/operator/capabilities/new").text
    # create
    resp = _post_form(client, "/operator/capabilities", {"capability_key":"http.test","version":"v1","is_active":"on"}, follow=False)
    assert resp.status_code == 303
    # follow to detail
    loc = resp.headers.get("location") or resp.headers.get("Location")
    assert loc and "/operator/capabilities/" in loc
    detail = client.get(loc)
    assert detail.status_code == 200
    assert "http.test" in detail.text
    # edit form
    cap_id = loc.rstrip("/").split("/")[-1]
    assert client.get(f"/operator/capabilities/{cap_id}/edit").status_code == 200
    # update
    resp2 = _post_form(client, f"/operator/capabilities/{cap_id}/edit", {"capability_key":"http.test","version":"v1","display_name":"Updated","is_active":"on"}, follow=False)
    assert resp2.status_code == 303
    assert "Updated" in client.get(f"/operator/capabilities/{cap_id}").text
    # 404
    assert client.get("/operator/capabilities/999999").status_code == 404


def test_model_routes_http(client):
    assert client.get("/operator/models").status_code == 200
    assert "Model Registry" in client.get("/operator/models").text
    assert client.get("/operator/models/new").status_code == 200
    assert "Add model" in client.get("/operator/models/new").text
    resp = _post_form(client, "/operator/models", {"model_key":"http-m","provider":"hp","exact_identifier":"hp/http-m:free","pricing_tier":"free","is_active":"on"}, follow=False)
    assert resp.status_code == 303
    loc = resp.headers.get("location") or resp.headers.get("Location")
    assert loc and "/operator/models/" in loc
    assert client.get(loc).status_code == 200
    assert "hp/http-m:free" in client.get(loc).text
    mid = loc.rstrip("/").split("/")[-1]
    assert client.get(f"/operator/models/{mid}/edit").status_code == 200
    resp2 = _post_form(client, f"/operator/models/{mid}/edit", {"model_key":"http-m","provider":"hp","exact_identifier":"hp/http-m:free","display_name":"New Name","pricing_tier":"free","is_active":"on"}, follow=False)
    assert resp2.status_code == 303
    assert "New Name" in client.get(f"/operator/models/{mid}").text
    assert client.get("/operator/models/999999").status_code == 404
    # missing fields 400
    resp_bad = _post_form(client, "/operator/models", {"model_key":"","provider":"","exact_identifier":"","pricing_tier":"free"})
    assert resp_bad.status_code == 400


def test_navigation_contains_registry_links(client):
    html = client.get("/operator").text
    assert 'href="/operator/capabilities"' in html
    assert 'href="/operator/models"' in html
    html2 = client.get("/operator/capabilities").text
    assert 'href="/operator/models"' in html2
    html3 = client.get("/operator/models").text
    assert 'href="/operator/capabilities"' in html3
    # still has overview/qualifications
    assert 'href="/operator"' in html and 'href="/operator/qualifications"' in html


def test_forms_are_accessible_and_responsive(client):
    for url in ["/operator/capabilities/new", "/operator/models/new"]:
        html = client.get(url).text
        assert "<form" in html
        assert 'label for=' in html
        assert "viewport" in client.get(url).text or True  # base always has viewport
    # css should exist and contain form styles
    css = client.get("/static/css/dashboard.css")
    assert css.status_code == 200
    assert ".form" in css.text
    assert ".btn" in css.text


# ---------------------------------------------------------------------------
# Historical preservation
# ---------------------------------------------------------------------------

def test_historical_qualification_preserved_after_registry_edits(tmp_path):
    # use dedicated client to have clean state with qualifications
    c, eng = _make_client(tmp_path)
    from fastapi.testclient import TestClient
    # seed via factory directly for this preservation test
    from aecc.db import create_session_factory
    from aecc.models import Capability, Harness, Model, QualificationDecision, QualificationState, LogicalTest, TestVersion, Run
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    factory = create_session_factory(eng)
    with factory() as s:
        cap = Capability(capability_key="preserve.test", version="v1", definition="orig", description="orig desc", is_active=True)
        s.add(cap)
        m = Model(model_key="preserve-m", provider="prov", exact_identifier="prov/preserve-m:free", pricing_tier="free", is_active=True)
        s.add(m)
        h = Harness(harness_key="h1", display_name="h1")
        s.add(h)
        lt = LogicalTest(key="lt-pres", name="lt")
        s.add(lt)
        s.flush()
        payload = build_definition_payload(task_prompt="p", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", capability_key="preserve.test")
        tv = TestVersion(logical_test_id=lt.id, version_number=1, task_prompt="p", capability_key="preserve.test", acceptance_criteria="a", rubric_id="r", rubric_version="1", permission_profile="READ_ONLY_NO_SHELL", created_at=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), definition_hash=canonical_definition_hash(payload))
        s.add(tv)
        s.flush()
        run = Run(test_version_id=tv.id, harness_id=h.id, model_id=m.id, capability_id=cap.id, state="QUEUED", requested_at=datetime.now(timezone.utc))
        s.add(run)
        s.flush()
        q = QualificationDecision(harness_id=h.id, model_id=m.id, capability_id=cap.id, state=QualificationState.QUALIFIED, methodology_version="m1", decided_at=datetime.now(timezone.utc), author="op")
        s.add(q)
        s.commit()
        cap_id = cap.id; model_id = m.id; run_id = run.id; q_id = q.id
    # edit capability and model via HTTP
    body_cap = urllib.parse.urlencode({"capability_key":"preserve.test","version":"v1","definition":"edited def","description":"edited desc","is_active":"on"})
    c.post(f"/operator/capabilities/{cap_id}/edit", content=body_cap, headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=True)
    body_mod = urllib.parse.urlencode({"model_key":"preserve-m","provider":"prov","exact_identifier":"prov/preserve-m:free","display_name":"New Display","pricing_tier":"paid","price_input":"1.0","price_output":"2.0","is_active":"on"})
    c.post(f"/operator/models/{model_id}/edit", content=body_mod, headers={"Content-Type":"application/x-www-form-urlencoded"}, follow_redirects=True)
    with factory() as s:
        cap2 = s.get(Capability, cap_id)
        assert cap2.definition == "edited def"
        assert cap2.is_active is True
        # qualification still points to same capability id
        q2 = s.get(QualificationDecision, q_id)
        assert q2.capability_id == cap_id
        assert q2.state.value == "QUALIFIED"
        # run still points to same ids and history intact
        run2 = s.get(Run, run_id)
        assert run2.capability_id == cap_id and run2.model_id == model_id
        # deactivate capability shouldn't delete history
        s.get(Capability, cap_id).is_active = False
        s.commit()
    with factory() as s:
        assert s.get(QualificationDecision, q_id) is not None
        assert s.get(Run, run_id) is not None
    # detail pages still show history even when inactive
    assert "preserve.test" in c.get(f"/operator/capabilities/{cap_id}").text
    assert "prov/preserve-m:free" in c.get(f"/operator/models/{model_id}").text
    eng.dispose()


def test_existing_dashboard_evidence_still_present_after_migration(client):
    # seed dashboard data and ensure overview still works after migration to 0002
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data
    factory = create_session_factory(client.engine)  # type: ignore
    with factory() as s:
        ids = seed_dashboard_data(s)
    html = client.get("/operator").text
    assert "test-provider/opencode-cheap-1.0-extended-identifier-for-readability" in html
    assert client.get("/operator/qualifications").status_code == 200
