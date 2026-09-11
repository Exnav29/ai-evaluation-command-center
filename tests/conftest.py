"""Pytest bootstrap: make `src/` importable without requiring `pip install`.

Also pins the execution layer's filesystem roots to per-test temp dirs so no
test can ever write run workspaces/evidence into the repository or the
operator's home, and no test can read fixtures from outside its own sandbox.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolated_execution_roots(tmp_path, monkeypatch):
    runs_root = tmp_path / "_aecc_runs"
    fixtures_root = tmp_path / "_aecc_fixtures"
    runs_root.mkdir()
    fixtures_root.mkdir()
    monkeypatch.setenv("AECC_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("AECC_FIXTURES_ROOT", str(fixtures_root))
    yield


_FAKE_OPENCODE_TEMPLATE = r'''#!/usr/bin/env python3
"""Fake `opencode` binary: records how it was invoked, then exits as told.

This is NOT a mock of subprocess.run: it is a real child process, so it proves
argv, cwd and environment actually crossed the process boundary. Behaviour is
embedded at install time, so the fake never depends on inherited environment
variables (the execution layer forwards only an allowlisted environment).
"""
import json, os, subprocess, sys, time
RECORD = {record!r}
PIDFILE = {pidfile!r}
GRANDCHILD = {grandchild!r}
EXIT = {exit_code!r}
STDOUT = {stdout!r}
STDERR = {stderr!r}
SLEEP = {sleep_seconds!r}
if RECORD:
    with open(RECORD, "w") as fh:
        json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(),
                    "env": {{k: v for k, v in os.environ.items()}}}}, fh)
if GRANDCHILD:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    if PIDFILE:
        with open(PIDFILE, "w") as fh:
            fh.write(str(child.pid))
sys.stdout.write(STDOUT)
sys.stderr.write(STDERR)
sys.stdout.flush()
sys.stderr.flush()
if SLEEP:
    time.sleep(SLEEP)
sys.exit(EXIT)
'''


@pytest.fixture()
def fake_opencode(tmp_path, monkeypatch):
    """Install a recording fake `opencode` on PATH. Returns the record path.

    Usage: ``record = fake_opencode(exit_code=0, stdout="...", stderr="...")``
    then read ``json.loads(record.read_text())`` after execution. Set
    ``sleep_seconds`` to make the fake outlive a short timeout, and
    ``grandchild_pid_file`` to spawn a long-lived descendant as well.
    """
    import os
    import stat

    bindir = tmp_path / "_fakebin"
    bindir.mkdir()

    def _install(
        exit_code: int = 0,
        stdout: str = "fake opencode stdout",
        stderr: str = "",
        *,
        sleep_seconds: float = 0.0,
        grandchild_pid_file: Path | str | None = None,
    ):
        record = tmp_path / "_opencode_record.json"
        exe = bindir / "opencode"
        exe.write_text(
            _FAKE_OPENCODE_TEMPLATE.format(
                record=str(record),
                pidfile=str(grandchild_pid_file) if grandchild_pid_file else None,
                grandchild=bool(grandchild_pid_file),
                exit_code=int(exit_code),
                stdout=stdout,
                stderr=stderr,
                sleep_seconds=float(sleep_seconds),
            )
        )
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        return record

    return _install
