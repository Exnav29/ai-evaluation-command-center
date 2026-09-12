"""Operator Dashboard V1 HTTP/rendered-page tests over seeded evidence.

Every test exercises real HTTP routes against an isolated migrated SQLite
database populated by ``seed_dashboard_data``. No production route depends
on hard-coded rows; assertions verify deterministic query semantics and
evidence-semantics preservation in rendered HTML.
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
    db_file = tmp_path / "dashboard.sqlite"
    command.upgrade(_alembic_config(db_file), "head")

    engine = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True)
    from aecc.db import apply_sqlite_pragmas

    apply_sqlite_pragmas(engine)
    from aecc.seed_dashboard import seed_dashboard_data
    from aecc.db import create_session_factory

    factory = create_session_factory(engine)
    with factory() as session:
        ids = seed_dashboard_data(session)

    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    test_client = TestClient(app)
    test_client.ids = ids  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        engine.dispose()


def _ids(client):
    return client.ids


def test_operator_overview_returns_200(client):
    response = client.get("/operator")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_qualification_overview_returns_200(client):
    response = client.get("/operator/qualifications")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_known_run_detail_returns_200(client):
    run_id = _ids(client)["runs"]["r1"]
    response = client.get(f"/operator/runs/{run_id}")
    assert response.status_code == 200
    assert f"Run #{run_id}" in response.text


def test_unknown_run_returns_404(client):
    response = client.get("/operator/runs/999999")
    assert response.status_code == 404


def test_recent_runs_newest_first(client):
    ids = _ids(client)["runs"]
    html = client.get("/operator").text
    positions = [html.index(f'data-run-id="{ids[k]}"') for k in ("r4", "r3", "r2", "r1")]
    assert positions == sorted(positions), "recent runs must render newest-first"


def test_exact_model_harness_capability_rendered(client):
    html = client.get("/operator").text
    assert "test-provider/opencode-cheap-1.0-extended-identifier-for-readability" in html
    assert "other-provider/frontier-x-2026.01-preview-long-exact-identifier" in html
    assert "opencode" in html
    assert "bug-fixing" in html
    assert "refactoring" in html
    run_id = _ids(client)["runs"]["r1"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "test-provider/opencode-cheap-1.0-extended-identifier-for-readability" in detail
    assert "opencode" in detail
    assert "bug-fixing" in detail


def test_latest_score_selected_and_history_preserved(client):
    run_id = _ids(client)["runs"]["r1"]
    overview = client.get("/operator").text
    assert "0.95" in overview
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "0.85" in detail
    assert "0.95" in detail
    assert "latest" in detail.lower()
    assert "correction after artifact recheck" in detail
    assert "initial scoring" in detail


def test_qualification_current_state_triple_keyed_and_history_preserved(client):
    html = client.get("/operator/qualifications").text
    assert "QUALIFIED" in html
    assert "RESTRICTED" in html
    assert "UNQUALIFIED" in html
    assert "SHADOW" in html
    assert "initial shadow qualification" in html
    assert "promotion after passing evidence" in html
    assert "opencode" in html and "bug-fixing" in html and "refactoring" in html
    run_id = _ids(client)["runs"]["r1"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "QUALIFIED" in detail and "SHADOW" in detail
    assert "current" in detail.lower()


def test_process_success_task_failure_not_presented_as_pass(client):
    run_id = _ids(client)["runs"]["r2"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "SUCCESS" in detail
    assert "MISSING" in detail
    assert "FAILED" in detail
    assert "FAIL" in detail
    assert ">PASS<" not in detail
    assert "exit code 0" in detail.lower() or ">0<" in detail


def test_unknown_not_presented_as_pass(client):
    run_id = _ids(client)["runs"]["r4"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "UNKNOWN" in detail
    assert "Not scored" in detail
    assert "badge-unknown" in detail
    assert ">PASS<" not in detail
    overview = client.get("/operator").text
    row = overview.split(f'data-run-id="{run_id}"')[1].split("</tr>")[0]
    assert "UNKNOWN" in row
    assert "badge-unknown" in row


def test_missing_cost_distinct_from_zero_cost(client):
    ids = _ids(client)["runs"]
    overview = client.get("/operator").text
    assert "$0.00" in overview
    assert "Not recorded" in overview
    r1 = client.get(f"/operator/runs/{ids['r1']}").text
    assert "$0.00" in r1
    r4 = client.get(f"/operator/runs/{ids['r4']}").text
    assert "Not recorded" in r4
    assert "$0.00" not in r4


def test_missing_tokens_distinct_from_zero_tokens(client):
    ids = _ids(client)["runs"]
    r4 = client.get(f"/operator/runs/{ids['r4']}").text
    assert "Not recorded / Not recorded" in r4
    r2 = client.get(f"/operator/runs/{ids['r2']}").text
    assert "0 / 0" in r2


def test_permission_denial_rendered_from_evidence(client):
    ids = _ids(client)["runs"]
    detail = client.get(f"/operator/runs/{ids['r3']}").text
    assert "permission-denied" in detail
    assert "not in profile" in detail
    overview = client.get("/operator").text
    r3 = _ids(client)["runs"]["r3"]
    row = overview.split(f'data-run-id="{r3}"')[1].split("</tr>")[0]
    assert "permission-denied" in row


def test_human_intervention_rendered_from_evidence(client):
    ids = _ids(client)["runs"]
    detail = client.get(f"/operator/runs/{ids['r3']}").text
    assert "human-intervention" in detail
    assert "prompt_clarification" in detail
    assert "operator clarified file scope" in detail
    overview = client.get("/operator").text
    r3 = _ids(client)["runs"]["r3"]
    row = overview.split(f'data-run-id="{r3}"')[1].split("</tr>")[0]
    assert "intervention" in row


def test_run_detail_renders_attempts_and_history(client):
    run_id = _ids(client)["runs"]["r1"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "Attempts" in detail
    assert "Score / verdict history" in detail
    assert "Interventions" in detail
    assert "Qualification for this harness" in detail
    assert "runs/r1/a1" in detail
    assert "pricing-snapshot-v3" in detail


def test_qualification_evidence_drillthrough_available(client):
    ids = _ids(client)["runs"]
    html = client.get("/operator/qualifications").text
    assert f'href="/operator/runs/{ids["r1"]}"' in html
    assert f'href="/operator/runs/{ids["r2"]}"' in html
    detail = client.get(f"/operator/runs/{ids['r1']}").text
    assert f'href="/operator/runs/{ids["r1"]}"' in detail
    assert client.get(f"/operator/runs/{ids['r1']}").status_code == 200


def test_navigation_and_semantic_html_present(client):
    html = client.get("/operator").text
    assert "<nav" in html
    assert "<h1>" in html
    assert "<table>" in html or "<table" in html
    assert "<th" in html
    # Qualification board stays reachable contextually from the overview charts.
    assert 'href="/operator/qualifications"' in html
    # The full technical index lives on Advanced, not in a persistent global subnav.
    adv = client.get("/advanced").text
    assert 'href="/operator"' in adv
    assert 'href="/operator/qualifications"' in adv
    detail = client.get(f"/operator/runs/{_ids(client)['runs']['r1']}").text
    assert "<h1>" in detail and "<h2" in detail
    assert "Back to overview" in detail


def test_unknown_badge_not_styled_as_success(client):
    css = client.get("/static/css/dashboard.css")
    assert css.status_code == 200
    assert ".badge-unknown" in css.text
    unknown_block = css.text.split(".badge-unknown")[1].split("}")[0]
    assert "#dcfce7" not in unknown_block
    assert "#166534" not in unknown_block
    html = client.get("/operator").text
    assert "badge-unknown" in html
    assert "badge-pass\">UNKNOWN" not in html


def test_summary_cards_derived_from_evidence(client):
    html = client.get("/operator").text
    assert 'data-testid="summary-total">4<' in html
    assert 'data-testid="summary-qualified">1<' in html
    assert 'data-testid="summary-unknown">1<' in html
    assert 'data-testid="summary-review">2<' in html


def test_excluded_evidence_remains_inspectable(client):
    ids = _ids(client)["runs"]
    detail = client.get(f"/operator/runs/{ids['r3']}").text
    assert "excluded" in detail.lower()
    assert "broken fixture path" in detail
    assert "aggregate-pass-rate" in detail
    overview = client.get("/operator").text
    assert f'data-run-id="{ids["r3"]}"' in overview
