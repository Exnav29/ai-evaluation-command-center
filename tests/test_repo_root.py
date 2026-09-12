"""Regression tests for repository-root resolution and root redirect.

A fresh-clone review found ``HERE.parents[2]`` in ``aecc.web`` resolving one
directory above the repository, which would place the default evidence
database outside the clone so sibling clones/worktrees silently share one
SQLite file. These tests pin the corrected behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_get_repo_root_contains_pyproject_and_is_repo_root():
    from aecc.execution import _get_repo_root as exec_root
    from aecc.web import _get_repo_root as web_root

    for root in (exec_root(), web_root()):
        assert root.is_dir()
        assert (root / "pyproject.toml").is_file()
        assert (root / "src" / "aecc" / "execution.py").is_file()
        assert (root / "src" / "aecc" / "web.py").is_file()
    # Both modules must agree on the same repository root.
    assert exec_root() == web_root() == ROOT


def test_default_db_path_resolves_beneath_repo_data(monkeypatch):
    monkeypatch.delenv("AECC_DB_PATH", raising=False)
    from aecc.execution import _db_path, _get_repo_root
    from aecc.web import _default_db_path

    root = _get_repo_root()
    assert _default_db_path() == root / "data" / "evaluations.sqlite"
    assert _db_path() == root / "data" / "evaluations.sqlite"


def test_default_db_path_respects_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom.sqlite"
    monkeypatch.setenv("AECC_DB_PATH", str(custom))
    from aecc.execution import _db_path
    from aecc.web import _default_db_path

    assert _default_db_path() == custom
    assert _db_path() == custom


def test_default_db_not_shared_by_sibling_clones(monkeypatch):
    """Sibling clones sharing a parent dir must not share one default DB."""
    monkeypatch.delenv("AECC_DB_PATH", raising=False)
    from aecc.execution import _get_repo_root
    from aecc.web import _default_db_path

    root = _get_repo_root()
    db = _default_db_path()
    # Fixed path lives inside this clone.
    assert db.parent == root / "data"
    # The old off-by-one bug resolved to <parent-of-repo>/data/..., which
    # sibling clones would share. That path must not be the default.
    buggy_shared = root.parent / "data" / "evaluations.sqlite"
    assert db != buggy_shared
    # Sibling-clone analogy: two clones under the same parent get distinct DBs.
    clone_a_db = root.parent / "clone-a" / "data" / "evaluations.sqlite"
    clone_b_db = root.parent / "clone-b" / "data" / "evaluations.sqlite"
    assert clone_a_db != clone_b_db


def test_default_fixtures_resolve_under_repo(monkeypatch):
    monkeypatch.delenv("AECC_FIXTURES_ROOT", raising=False)
    from aecc.execution import _fixtures_root, _get_repo_root

    assert _fixtures_root() == _get_repo_root() / "fixtures"


def test_alembic_lookup_resolves_repo_ini():
    from aecc.web import _get_repo_root

    ini = _get_repo_root() / "alembic.ini"
    assert ini.is_file()


def test_containment_rejects_workspace_inside_repo():
    from aecc.execution import _get_repo_root, _validate_workspace

    root = _get_repo_root()
    for candidate in (root / "runs" / "999" / "workspace", root / "src", root / "data"):
        err = _validate_workspace(candidate)
        assert err is not None and "inside the AECC repository" in err, candidate


def test_root_redirects_to_operator(tmp_path):
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    db_file = tmp_path / "root-redirect.sqlite"
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_file}", future=True)
    try:
        from aecc.web import create_app
        from fastapi.testclient import TestClient

        app = create_app(engine=engine)
        client = TestClient(app, follow_redirects=False)
        response = client.get("/")
        assert response.status_code in (301, 302, 303, 307, 308)
        assert response.headers["location"] == "/operator"
    finally:
        engine.dispose()
