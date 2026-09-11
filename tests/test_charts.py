"""Milestone 1 Charts tests: analytics correctness + populated rendering.

Covers evidence rules (UNKNOWN stays unknown, missing never zero, demo
excluded) and HTTP rendering (ECharts panels, JSON payloads, fallback tables,
populated demo rendering).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _alembic_config(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "charts.sqlite"
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
    tc = TestClient(app)
    tc.ids = ids  # type: ignore[attr-defined]
    tc.engine = engine  # type: ignore[attr-defined]
    try:
        yield tc
    finally:
        engine.dispose()


@pytest.fixture()
def empty_client(tmp_path):
    db_file = tmp_path / "charts-empty.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas

    apply_sqlite_pragmas(engine)
    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    tc = TestClient(app)
    tc.engine = engine  # type: ignore[attr-defined]
    try:
        yield tc
    finally:
        engine.dispose()


def _session(client):
    from aecc.db import create_session_factory

    return create_session_factory(client.engine)()


def _chart_json(html: str, script_id: str) -> dict:
    m = re.search(
        rf'<script id="{re.escape(script_id)}" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert m, f"missing chart payload {script_id}"
    return json.loads(m.group(1))


# --- Query correctness ---

def test_qualification_distribution_counts_stored_current(client):
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_qualification_distribution(s)
    assert payload["labels"] == ["QUALIFIED", "SHADOW", "RESTRICTED", "UNQUALIFIED", "NOT_AUTHORIZED"]
    # seed: QUALIFIED x1, RESTRICTED x1, UNQUALIFIED x1 (SHADOW superseded, not counted)
    assert payload["counts"] == [1, 0, 1, 1, 0]
    assert payload["triples_total"] == 3


def test_verdict_chart_unknown_never_pass_and_excluded_separate(client):
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_verdict_by_model_harness(s)
    by_label = {g["label"]: g for g in payload["groups"]}
    # r1 PASS group
    assert by_label["opencode + cheap-free"]["counts"]["PASS"] == 1
    # r2 FAIL group
    assert by_label["opencode + frontier-x"]["counts"]["FAIL"] == 1
    # r3 carries an exclusion event -> EXCLUDED bucket, never NEEDS_REVIEW/pass
    assert by_label["opencode-strict + cheap-free"]["counts"]["EXCLUDED"] == 1
    assert by_label["opencode-strict + cheap-free"]["evaluated"] == 0
    assert by_label["opencode-strict + cheap-free"]["pass_rate"] is None
    # r4 unscored -> UNKNOWN bucket
    assert by_label["opencode-strict + frontier-x"]["counts"]["UNKNOWN"] == 1
    assert by_label["opencode-strict + frontier-x"]["pass_rate"] is None


def test_cost_chart_zero_distinct_from_unknown(client):
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_cost_by_model_harness(s)
    by_label = {g["label"]: g for g in payload["groups"]}
    free = by_label["opencode + cheap-free"]
    assert free["n_known"] == 1 and free["n_unknown"] == 0
    assert free["sum_known"] == 0.0 and free["avg_known"] == 0.0
    assert free["has_zero_cost"] is True
    unknown = by_label["opencode-strict + frontier-x"]
    assert unknown["n_known"] == 0 and unknown["n_unknown"] == 1
    assert unknown["sum_known"] is None and unknown["avg_known"] is None


def test_elapsed_chart_missing_never_zero(client):
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_elapsed_by_model_harness(s)
    by_label = {g["label"]: g for g in payload["groups"]}
    assert by_label["opencode + cheap-free"]["avg_known"] == pytest.approx(92.0)
    unknown = by_label["opencode-strict + frontier-x"]
    assert unknown["avg_known"] is None
    assert unknown["n_unknown"] == 1


def test_scores_chart_unscored_never_zero(client):
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_scores_by_model_harness(s)
    by_label = {g["label"]: g for g in payload["groups"]}
    assert by_label["opencode + cheap-free"]["avg_scored"] == pytest.approx(0.95)
    assert by_label["opencode-strict + frontier-x"]["n_scored"] == 0
    assert by_label["opencode-strict + frontier-x"]["avg_scored"] is None
    assert by_label["opencode-strict + frontier-x"]["n_unscored_unknown"] == 1


def test_demo_excluded_by_default(client, tmp_path):
    # Demo rows live in a separate database in practice (same keys, is_demo=1).
    # Build a demo-only DB and verify default exclusion vs opt-in.
    from aecc import chart_queries as cq

    db_file = tmp_path / "charts-demo.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    demo_engine = sa.create_engine(f"sqlite:///{db_file}", future=True)
    from aecc.db import create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data

    demo_factory = create_session_factory(demo_engine)
    with demo_factory() as s:
        seed_dashboard_data(s, is_demo=True)
    with demo_factory() as s:
        assert cq.fetch_chart_qualification_distribution(s)["triples_total"] == 0
        assert cq.fetch_chart_verdict_by_model_harness(s)["groups"] == []
        assert cq.fetch_chart_qualification_distribution(s, include_demo=True)["triples_total"] == 3
        assert sum(
            g["runs_total"]
            for g in cq.fetch_chart_verdict_by_model_harness(s, include_demo=True)["groups"]
        ) == 4
    demo_engine.dispose()
    # Real DB still reports real evidence only.
    with _session(client) as s:
        assert cq.fetch_chart_qualification_distribution(s)["triples_total"] == 3


def test_empty_db_returns_empty_not_zeros(empty_client):
    with _session(empty_client) as s:
        from aecc import chart_queries as cq

        assert cq.fetch_chart_qualification_distribution(s)["meta"]["empty"] is True
        assert cq.fetch_chart_verdict_by_model_harness(s)["groups"] == []
        cost = cq.fetch_chart_cost_by_model_harness(s)
        assert cost["groups"] == [] and cost["meta"]["empty"] is True
        elapsed = cq.fetch_chart_elapsed_by_model_harness(s)
        assert elapsed["groups"] == []
        scores = cq.fetch_chart_scores_by_model_harness(s)
        assert scores["groups"] == []


def test_latest_revision_and_attempt_used(client):
    # r1 has two score revisions (0.85 superseded by 0.95); chart must use 0.95
    with _session(client) as s:
        from aecc import chart_queries as cq

        payload = cq.fetch_chart_scores_by_model_harness(s)
    by_label = {g["label"]: g for g in payload["groups"]}
    assert by_label["opencode + cheap-free"]["values_scored"] == [pytest.approx(0.95)]


# --- Rendered pages ---

def test_overview_renders_all_five_charts_with_fallbacks(client):
    html = client.get("/operator").text
    for cid in (
        "overview-chart-qual",
        "overview-chart-verdict",
        "overview-chart-cost",
        "overview-chart-elapsed",
        "overview-chart-scores",
    ):
        assert f'id="{cid}"' in html
        assert f'id="{cid}-data"' in html
    assert "/static/vendor/echarts.min.js" in html
    assert "/static/js/charts.js" in html
    assert html.count("Underlying values") >= 5
    # fallback tables expose real numbers, unknown explicitly labeled
    assert "Not recorded" in html
    assert "UNKNOWN" in html
    # drill-down links present
    assert "/operator/runs/" in html
    # JSON payloads parse and carry expected types
    qual = _chart_json(html, "overview-chart-qual-data")
    assert qual["type"] == "qualification_state_distribution"
    verdict = _chart_json(html, "overview-chart-verdict-data")
    assert verdict["type"] == "verdict_by_model_harness" and len(verdict["groups"]) == 4


def test_compare_renders_filtered_charts(client):
    html = client.get("/operator/compare").text
    assert 'id="compare-chart-verdict"' in html
    assert 'id="compare-chart-cost-data"' in html
    # filter to one capability still renders charts section
    with _session(client) as s:
        import sqlalchemy as _sa
        from aecc.models import Capability

        cap_id = s.scalar(_sa.select(Capability.id).limit(1))
    resp = client.get(f"/operator/compare?capability_id={cap_id}")
    assert resp.status_code == 200
    fhtml = resp.text
    assert 'id="compare-chart-verdict"' in fhtml
    _ = _chart_json(fhtml, "compare-chart-verdict-data")


def test_qualification_page_renders_charts(client):
    html = client.get("/operator/qualification").text
    assert 'id="qualpage-chart-qual"' in html
    assert 'id="qualpage-chart-scores-data"' in html
    qual = _chart_json(html, "qualpage-chart-qual-data")
    assert qual["triples_total"] == 3


def test_empty_pages_render_empty_states(empty_client):
    html = empty_client.get("/operator").text
    assert "No qualification decisions yet" in html or "No completed evaluation evidence" in html
    assert "Underlying values" in html
    qual = _chart_json(html, "overview-chart-qual-data")
    assert qual["triples_total"] == 0


def test_populated_demo_rendering_labels_and_excludes(tmp_path):
    # Populated demo DB renders labeled demo rows; charts opt-in shows them.
    from aecc import chart_queries as cq

    db_file = tmp_path / "charts-demo-pop.sqlite"
    command.upgrade(_alembic_config(db_file), "head")
    demo_engine = sa.create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True
    )
    from aecc.db import apply_sqlite_pragmas, create_session_factory
    from aecc.seed_dashboard import seed_dashboard_data

    apply_sqlite_pragmas(demo_engine)
    demo_factory = create_session_factory(demo_engine)
    with demo_factory() as s:
        seed_dashboard_data(s, is_demo=True)
    from aecc.web import create_app
    from fastapi.testclient import TestClient

    demo_client = TestClient(create_app(engine=demo_engine))
    html = demo_client.get("/operator").text
    # demo banner + labeled rows render
    assert "demo data" in html.lower()
    assert "demo</span>" in html
    # default charts exclude demo (empty), opt-in restores evidence
    qual = _chart_json(html, "overview-chart-qual-data")
    assert qual["triples_total"] == 0
    with demo_factory() as s:
        assert cq.fetch_chart_qualification_distribution(s, include_demo=True)["triples_total"] == 3
    demo_engine.dispose()


def test_charts_js_and_vendor_served(client):
    js = client.get("/static/js/charts.js")
    assert js.status_code == 200
    assert "echarts" in js.text.lower()
    vendor = client.get("/static/vendor/echarts.min.js")
    assert vendor.status_code == 200
    assert len(vendor.content) > 100000  # real ECharts bundle, not a stub
