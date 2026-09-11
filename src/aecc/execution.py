"""Execution worker/service layer.

Executes a registered TestVersion against an exact Model through a declared
harness adapter and records the result as evidence.

Containment model (READ THIS BEFORE CHANGING)
---------------------------------------------
This module runs the harness as a host subprocess. That is a *harness-level*
guard, not an OS/container boundary. Per ARCHITECTURE_BASELINE_V1 §9.5, until
container containment is verified, the host adapter is only permitted to run
read-only / no-shell permission profiles. Profiles that grant write or shell
authority are refused with INFRASTRUCTURE_FAILURE (not-configured) rather than
executed under a false claim of isolation.

A per-run workspace is only accepted when it is genuinely outside every
protected root (the AECC repository, the evidence database, the runs root of
other runs, the operator's home) and not nested inside any git worktree.
OpenCode resolves its project by walking up to the enclosing git root, so a
workspace *underneath* the AECC repository would make the AECC repository the
agent's project. A different cwd is not isolation.

Source preparation
------------------
``TestVersion.source_fixture_ref`` names a path relative to a server-owned
fixture root (``AECC_FIXTURES_ROOT``, default ``<repo>/fixtures``). It is
materialized into the fresh workspace (git clone + detached checkout of
``source_commit`` when the fixture is a git repository; copy otherwise). If it
cannot be materialized exactly, execution is refused. No placeholders are ever
fabricated, and nothing is written into the subject workspace by AECC.

Outcomes
--------
Process outcome comes from the exit code. Task/deliverable/repo outcomes stay
UNKNOWN: there is no scoring automation and exit 0 never implies task success.
Raw stdout/stderr and the exact invocation are persisted under the runs root
so ``Attempt.raw_evidence_location`` points at real evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aecc.models import (
    Attempt,
    AuditEvent,
    Capability,
    DeliverableOutcome,
    FailureClassification,
    Harness,
    Model,
    ProcessOutcome,
    RepoModificationOutcome,
    Run,
    RunState,
    TaskOutcome,
    TestVersion,
)

NOT_CONFIGURED = "not-configured"


@dataclass
class HarnessResult:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Server-owned permission profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionPolicy:
    """Harness-neutral description of what an evaluated agent may do."""

    name: str
    workspace_edit: bool
    shell: bool
    network_tools: bool
    host_enforceable: bool  # True only if a host subprocess can honestly enforce it


PERMISSION_PROFILES: dict[str, PermissionPolicy] = {
    # Planning-style evaluation: read the workspace, nothing else. This is the
    # only profile the host adapter may run before container containment exists.
    "READ_ONLY_NO_SHELL": PermissionPolicy("READ_ONLY_NO_SHELL", False, False, False, True),
    # The following require an OS/container boundary (§9.1). Defined so the
    # refusal reason is explicit rather than "unknown profile".
    "READ_ONLY_DIAGNOSTIC": PermissionPolicy("READ_ONLY_DIAGNOSTIC", False, True, False, False),
    "WORKSPACE_WRITE_RESTRICTED": PermissionPolicy("WORKSPACE_WRITE_RESTRICTED", True, False, False, False),
    "WORKSPACE_WRITE_AND_SHELL_CONTAINED": PermissionPolicy("WORKSPACE_WRITE_AND_SHELL_CONTAINED", True, True, False, False),
}


def resolve_permission_policy(profile: Optional[str]) -> tuple[Optional[PermissionPolicy], Optional[str]]:
    """Return (policy, None) if the profile is host-enforceable, else (None, reason)."""
    key = (profile or "").strip()
    if not key:
        return None, "permission profile missing: execution authority must come from a server-owned profile"
    policy = PERMISSION_PROFILES.get(key)
    if policy is None:
        return None, f"permission profile '{key}' is not a server-owned profile; refusing to infer authority"
    if not policy.host_enforceable:
        return None, (
            f"permission profile '{key}' grants write/shell authority and requires OS/container containment; "
            f"the host OpenCode adapter only supports read-only/no-shell profiles until containment is verified"
        )
    return policy, None


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HarnessAdapter:
    """Contract a harness must satisfy to be executed.

    Future adapters (Codex, Claude Code, Kimi, ...) register here. Each adapter
    owns argv construction and how a PermissionPolicy is projected onto that
    harness's own configuration surface. Nothing outside this registry may
    know harness-specific flags.
    """

    key: str
    binary: str
    build_argv: Callable[[TestVersion, Model, Path], list[str]]
    build_env: Callable[[PermissionPolicy, Path], dict[str, str]]


def _opencode_argv(tv: TestVersion, model: Model, workspace: Path) -> list[str]:
    # ``--`` terminates option parsing so a prompt beginning with ``-`` cannot be
    # interpreted as a flag (verified: without it ``--version`` as a prompt
    # prints the version instead of running). ``--auto`` is never passed.
    # ``--agent`` is pinned to the server-owned evaluation agent so a globally
    # configured default agent (plan/something custom) can never change what is
    # being evaluated.
    return [
        "opencode",
        "run",
        "--dir",
        str(workspace),
        "--agent",
        OPENCODE_EVAL_AGENT,
        "--model",
        model.exact_identifier.strip(),
        "--",
        tv.task_prompt,
    ]


# Server-owned agent name projected into ``OPENCODE_CONFIG_CONTENT`` and pinned
# on the command line. The evaluated harness must never pick up the operator's
# configured default agent.
OPENCODE_EVAL_AGENT = "aecc-eval"


def _opencode_permission(policy: PermissionPolicy) -> dict:
    """Explicit, closed permission set for a read-only planning evaluation.

    Every gateable permission is named; ``*`` denies anything not listed so an
    operator/global config can never widen authority by omission. ``read`` is
    restricted to the workspace and the usual secret files are refused.
    """
    deny_allow = lambda flag: "allow" if flag else "deny"  # noqa: E731
    return {
        "*": "deny",
        "read": {
            "*": "allow",
            "*.env": "deny",
            "*.env.*": "deny",
            "*.env.example": "allow",
        },
        "glob": "allow",
        "grep": "allow",
        "list": "allow",
        "edit": deny_allow(policy.workspace_edit),
        "bash": deny_allow(policy.shell),
        "webfetch": deny_allow(policy.network_tools),
        "websearch": deny_allow(policy.network_tools),
        "task": "deny",
        "skill": "deny",
        "todowrite": "deny",
        "todoread": "deny",
        "lsp": "deny",
        "question": "deny",
        "doom_loop": "deny",
        # The evaluated agent must never reach outside its workspace.
        "external_directory": "deny",
    }


# Environment variables that are safe/required to pass to the evaluated
# harness. Secrets are NOT inherited wholesale (ARCH §9.4): only these system
# variables plus scoped provider credentials are forwarded.
_ENV_EXACT_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TERM",
        "TMPDIR",
    }
)
_ENV_PREFIX_ALLOWLIST = ("XDG_",)
# Provider credentials are scoped per known provider rather than inherited.
_PROVIDER_KEY_ALLOWLIST = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENCODE_API_KEY",
        "ZEN_API_KEY",
    }
)


def _build_harness_env() -> dict[str, str]:
    """Return a minimal, allowlisted environment for the evaluated process."""
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ENV_EXACT_ALLOWLIST or key in _PROVIDER_KEY_ALLOWLIST:
            env[key] = value
        elif any(key.startswith(prefix) for prefix in _ENV_PREFIX_ALLOWLIST):
            env[key] = value
    env.setdefault("PATH", os.defpath)
    return env


def _opencode_env(policy: PermissionPolicy, workspace: Path) -> dict[str, str]:
    """Project a PermissionPolicy onto OpenCode's config surface.

    ``OPENCODE_CONFIG_CONTENT`` is merged last, so these rules override both
    the operator's global config and anything a fixture ships in-tree. The
    evaluated process receives a minimal allowlisted environment rather than a
    copy of the operator's shell (ARCH §9.4).
    """
    permission = _opencode_permission(policy)
    env = _build_harness_env()
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "permission": permission,
            "agent": {
                OPENCODE_EVAL_AGENT: {
                    "description": "Server-owned AECC evaluation agent (read-only; do not modify).",
                    "mode": "primary",
                    "permission": permission,
                }
            },
        }
    )
    # Do not let a fixture's own opencode.json/plugins, the operator's config,
    # or external skill trees alter the evaluated harness.
    env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] = "1"
    env["OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"] = "1"
    env["OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"] = "1"
    return env


ADAPTERS: dict[str, HarnessAdapter] = {
    "opencode": HarnessAdapter(key="opencode", binary="opencode", build_argv=_opencode_argv, build_env=_opencode_env),
}


def _is_opencode_available() -> bool:
    """Return True if the ``opencode`` binary is available on PATH."""
    return shutil.which("opencode") is not None


def resolve_adapter(harness: Optional[Harness]) -> Optional[HarnessAdapter]:
    """Return the declared adapter for a harness, or None.

    Only an explicit ``{"adapter": "<key>"}`` declaration in ``config_snapshot``
    counts. Version/build/mode metadata never makes a harness runnable.
    """
    if harness is None or not harness.config_snapshot:
        return None
    try:
        data = json.loads(harness.config_snapshot)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    key = data.get("adapter")
    if key is None and data.get("opencode_adapter") is True:
        key = "opencode"
    if not isinstance(key, str):
        return None
    return ADAPTERS.get(key)


def is_harness_runnable(harness: Optional[Harness]) -> bool:
    return resolve_adapter(harness) is not None


def _adapter_binary_available(adapter: HarnessAdapter) -> bool:
    if adapter.key == "opencode":
        return _is_opencode_available()  # kept as a seam for tests
    return shutil.which(adapter.binary) is not None


# ---------------------------------------------------------------------------
# Filesystem roots and containment
# ---------------------------------------------------------------------------

def _get_repo_root() -> Path:
    """Return the AECC repository root (src/aecc/execution.py -> parents[2])."""
    return Path(__file__).resolve().parents[2]


def _db_path() -> Optional[Path]:
    override = os.environ.get("AECC_DB_PATH")
    if override:
        return Path(override)
    return _get_repo_root() / "data" / "evaluations.sqlite"


def _runs_root() -> Path:
    """Root for per-run workspaces and evidence. Must be outside the AECC repo.

    ``AECC_RUNS_ROOT`` overrides; default is ``$XDG_STATE_HOME/aecc/runs`` or
    ``~/.local/state/aecc/runs``. The temp dir is the last resort.
    """
    override = os.environ.get("AECC_RUNS_ROOT")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "aecc" / "runs"
    try:
        return Path.home() / ".local" / "state" / "aecc" / "runs"
    except Exception:
        import tempfile

        return Path(tempfile.gettempdir()) / "aecc-runs"


def _fixtures_root() -> Path:
    override = os.environ.get("AECC_FIXTURES_ROOT")
    return Path(override) if override else _get_repo_root() / "fixtures"


def _resolve_lenient(p: Path) -> Path:
    try:
        return p.resolve()
    except Exception:
        return p.absolute()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _enclosing_git_root(ws: Path) -> Optional[Path]:
    """Return the nearest git worktree root strictly above ``ws``, else None.

    ``.git`` may be a directory (normal checkout), a file (linked worktree or
    submodule), or a broken symlink; all are treated as a repository boundary.
    Only ancestors are considered: the workspace itself is allowed to be the
    subject repository (e.g. a materialized git fixture), which is the project
    OpenCode should adopt.
    """
    for ancestor in ws.parents:
        dotgit = ancestor / ".git"
        if dotgit.exists() or dotgit.is_symlink():
            return ancestor
    return None


def _protected_roots() -> list[tuple[str, Path, bool]]:
    """(label, path, reject_inside). A workspace may never equal or contain a
    protected path. For the AECC repository it may not be *inside* it either
    (the harness would adopt the repository as its project). Being inside the
    operator's home (e.g. ~/.local/state) is normal, so only equality and
    containment are rejected there; the same applies to the DB file."""
    roots: list[tuple[str, Path, bool]] = [("AECC repository", _resolve_lenient(_get_repo_root()), True)]
    db = _db_path()
    if db is not None:
        roots.append(("evidence database", _resolve_lenient(db), False))
    try:
        roots.append(("operator home directory", _resolve_lenient(Path.home()), False))
    except Exception:
        pass
    return roots


def _validate_workspace(workspace: Optional[Path | str], *, require_fresh: bool = True) -> Optional[str]:
    """Validate that workspace is an explicit, genuinely separate directory.

    Returns None if acceptable, else a reason. Rules:
    - must be provided and non-empty (no implicit cwd)
    - must not be filesystem root
    - must not be or contain any protected path (AECC repo, evidence DB,
      operator home), and must not be inside the AECC repository. A directory
      *under* the AECC repository is NOT isolated.
    - no ancestor may be a git worktree (same reason)
    - if ``require_fresh`` and it already exists it must be an empty directory
    """
    if workspace is None or not str(workspace).strip():
        return "workspace required: real evaluations must run in an explicit per-run isolated workspace, never AECC repo/current working directory"
    ws = _resolve_lenient(Path(workspace))
    if ws == Path(ws.anchor):
        return "workspace cannot be filesystem root"
    for label, root, reject_inside in _protected_roots():
        if ws == root:
            return f"refusing to execute in {label} ({root}): not an isolated workspace"
        if reject_inside and _is_within(ws, root):
            return f"refusing workspace {ws}: it is inside the {label} ({root}); a subdirectory of the repository is not isolation"
        if _is_within(root, ws):
            return f"refusing workspace {ws}: it contains the {label} ({root})"
    git_root = _enclosing_git_root(ws)
    if git_root is not None:
        return f"refusing workspace {ws}: nested inside git worktree {git_root}; the harness would treat that repository as its project"
    if ws.exists():
        if not ws.is_dir():
            return f"workspace is not a directory: {ws}"
        if require_fresh and any(ws.iterdir()):
            return f"refusing workspace {ws}: not empty; each run requires a fresh workspace"
    return None


def _default_workspace_for_run(run_id: int) -> Path:
    return _runs_root() / str(run_id) / "workspace"


def _evidence_dir_for_attempt(run_id: int, attempt_number: int) -> Path:
    return _runs_root() / str(run_id) / f"a{attempt_number}"


# ---------------------------------------------------------------------------
# Source materialization
# ---------------------------------------------------------------------------

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _validate_commit_sha(commit: Optional[str]) -> Optional[str]:
    """Return None if ``commit`` is a well-formed git object id, else a reason."""
    if commit is None:
        return None
    value = commit.strip()
    if not value:
        return "source_commit is empty"
    if not _COMMIT_SHA_RE.match(value):
        return f"source_commit {commit!r} is not a 7-40 character lowercase hex git object id"
    return None


def _find_symlink(root: Path, *, skip_git: bool = True) -> Optional[Path]:
    """Return the first symlink under ``root``, else None (never follows links)."""
    if root.is_symlink():
        return root
    if not root.is_dir():
        return None
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if skip_git and Path(dirpath).name == ".git":
            dirnames[:] = []
            continue
        for name in list(dirnames) + list(filenames):
            candidate = Path(dirpath) / name
            if candidate.is_symlink():
                return candidate
    return None


def _validate_fixture_ref(ref: str) -> tuple[Optional[Path], Optional[str]]:
    """Resolve a fixture ref against the server-owned fixture root.

    Absolute paths, parent traversal, symlinked components, and anything
    resolving outside the root are refused. Returns (path, None) or reason.
    """
    raw = (ref or "").strip()
    if not raw:
        return None, "source_fixture_ref is empty"
    if "\x00" in raw or "\\" in raw:
        return None, f"source_fixture_ref contains an illegal character: {raw!r}"
    p = Path(raw)
    if p.is_absolute() or raw.startswith("~"):
        return None, f"source_fixture_ref must be relative to the fixture root, got absolute path: {raw}"
    if any(part in ("..", "") for part in p.parts if part != "."):
        return None, f"source_fixture_ref must not contain parent traversal: {raw}"
    root = _resolve_lenient(_fixtures_root())
    # Walk each lexical component so a symlink partway down cannot be used to
    # hop out of the fixture root (resolve alone hides which component linked).
    cur = root
    for part in p.parts:
        cur = cur / part
        if cur.is_symlink():
            return None, f"source_fixture_ref {raw!r} traverses symlink {cur}; symlinked fixture paths are refused"
    target = _resolve_lenient(root / p)
    if not _is_within(target, root):
        return None, f"source_fixture_ref resolves outside fixture root {root}: {raw}"
    if not target.exists():
        return None, f"fixture not found under {root}: {raw} (no placeholder is fabricated)"
    return target, None



def _tree_digest(root: Path) -> str:
    """Deterministic sha256 over relative paths + contents (excluding .git)."""
    h = hashlib.sha256()
    if root.is_file():
        h.update(root.name.encode())
        h.update(root.read_bytes())
        return h.hexdigest()
    for path in sorted(p for p in root.rglob("*") if ".git" not in p.parts):
        rel = path.relative_to(root).as_posix().encode()
        if path.is_dir():
            h.update(b"D" + rel)
        elif path.is_file():
            h.update(b"F" + rel)
            h.update(path.read_bytes())
    return h.hexdigest()


def _git(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def _prepare_run_workspace(workspace: Path, tv: TestVersion) -> tuple[Optional[dict], Optional[str]]:
    """Materialize the registered source into a fresh workspace.

    Returns (source_state, None) on success, else (None, reason). Never writes
    AECC metadata into the subject workspace.
    """
    workspace = _resolve_lenient(Path(workspace))
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return None, f"failed to create workspace {workspace}: {e}"
    if not workspace.is_dir():
        return None, f"workspace is not a directory: {workspace}"

    state: dict = {"fixture_ref": tv.source_fixture_ref, "source_commit": tv.source_commit}

    if not tv.source_fixture_ref:
        if tv.source_commit:
            return None, "source_commit is set but no source_fixture_ref names a repository to check it out from"
        state["materialized"] = "empty-workspace"
        return state, None

    sha_err = _validate_commit_sha(tv.source_commit)
    if sha_err is not None:
        return None, sha_err

    src, err = _validate_fixture_ref(tv.source_fixture_ref)
    if err is not None:
        return None, err
    assert src is not None
    state["fixture_path"] = str(src)

    try:
        if src.is_dir() and (src / ".git").exists():
            if shutil.which("git") is None:
                return None, "git binary not available; cannot materialize a git fixture"
            if _find_symlink(src, skip_git=True) is not None:
                return None, f"fixture {tv.source_fixture_ref} contains symlinks; refusing ambiguous source"
            clone = _git(["clone", "--quiet", "--no-hardlinks", str(src), str(workspace)], cwd=workspace.parent)
            if clone.returncode != 0:
                return None, f"git clone of fixture failed: {clone.stderr.strip()[:500]}"
            if tv.source_commit:
                co = _git(["checkout", "--quiet", "--detach", tv.source_commit], cwd=workspace)
                if co.returncode != 0:
                    return None, f"git checkout of source_commit {tv.source_commit} failed: {co.stderr.strip()[:500]}"
                resolved = _git(["rev-parse", f"{tv.source_commit}^{{commit}}"], cwd=workspace)
                if resolved.returncode != 0:
                    return None, f"registered source_commit {tv.source_commit} does not resolve to a commit"
                resolved_sha = resolved.stdout.strip()
            else:
                resolved = _git(["rev-parse", "HEAD"], cwd=workspace)
                if resolved.returncode != 0:
                    return None, "could not resolve HEAD after checkout"
                resolved_sha = resolved.stdout.strip()
            head = _git(["rev-parse", "HEAD"], cwd=workspace)
            if head.returncode != 0:
                return None, "could not resolve HEAD after checkout"
            head_sha = head.stdout.strip()
            # Exact identity: the checked-out commit must be precisely the
            # registered object id, not merely share a prefix.
            if tv.source_commit and head_sha != resolved_sha:
                return None, f"materialized HEAD {head_sha} does not match registered source_commit {resolved_sha}"
            if _find_symlink(workspace, skip_git=True) is not None:
                return None, "materialized fixture contains symlinks; refusing ambiguous source"
            state["materialized"] = "git-clone"
            state["materialized_commit"] = head_sha
        else:
            if tv.source_commit:
                return None, f"source_commit {tv.source_commit} is set but fixture {tv.source_fixture_ref} is not a git repository"
            if _find_symlink(src) is not None:
                return None, f"fixture {tv.source_fixture_ref} contains symlinks; refusing ambiguous source"
            if src.is_dir():
                shutil.copytree(src, workspace, dirs_exist_ok=True, symlinks=False)
                state["materialized"] = "copy-tree"
            else:
                shutil.copy2(src, workspace / src.name)
                state["materialized"] = "copy-file"
        if _find_symlink(workspace, skip_git=True) is not None:
            return None, "materialized workspace contains symlinks; refusing ambiguous source"
        state["tree_sha256"] = _tree_digest(workspace)
    except subprocess.TimeoutExpired:
        return None, "timed out materializing fixture"
    except Exception as e:
        return None, f"failed to prepare fixture {tv.source_fixture_ref}: {e}"
    return state, None



# ---------------------------------------------------------------------------
# Preflight and invocation
# ---------------------------------------------------------------------------

def check_preflight(harness: Optional[Harness], model: Optional[Model], tv: Optional[TestVersion], workspace: Optional[Path | str] = None, *, require_fresh_workspace: bool = True) -> Optional[str]:
    """Return None if runnable, else a reason (all reasons are infrastructure/not-configured).

    ``require_fresh_workspace=False`` is used after the source has been
    materialized into the (previously empty) workspace.
    """
    adapter = resolve_adapter(harness)
    if adapter is None:
        key = harness.harness_key if harness is not None else "unknown"
        return f"harness not configured: no runnable adapter for harness '{key}'"
    ws_err = _validate_workspace(workspace, require_fresh=require_fresh_workspace)
    if ws_err is not None:
        return ws_err
    if tv is None or not tv.task_prompt or not tv.task_prompt.strip():
        return "test version prompt missing"
    _, perm_err = resolve_permission_policy(tv.permission_profile)
    if perm_err is not None:
        return perm_err
    if not _adapter_binary_available(adapter):
        return f"{adapter.binary} binary not available"
    if model is None or not model.exact_identifier or not model.exact_identifier.strip():
        return "model exact_identifier missing"
    return None


def build_opencode_command(tv: TestVersion, model: Model, workspace: Optional[Path | str] = None) -> list[str]:
    """Build argv for ``opencode run`` (argv list, never shell)."""
    if workspace is None or not str(workspace).strip():
        raise ValueError("workspace required: real evaluations must run in an explicit per-run isolated workspace, never AECC repo/current working directory")
    ws_err = _validate_workspace(workspace)
    if ws_err is not None:
        raise ValueError(ws_err)
    if not model.exact_identifier or not model.exact_identifier.strip():
        raise ValueError("model exact_identifier missing")
    if not tv.task_prompt or not tv.task_prompt.strip():
        raise ValueError("test version prompt missing")
    return ADAPTERS["opencode"].build_argv(tv, model, Path(workspace))


def _not_configured(reason: str, elapsed: float = 0.0) -> HarnessResult:
    return HarnessResult(exit_code=None, stdout="", stderr=reason, elapsed_seconds=elapsed, timed_out=False, error=NOT_CONFIGURED)


def _terminate_process_group(proc: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    """Terminate the whole process group of ``proc``, then SIGKILL if needed.

    A harness may spawn children (e.g. a model call server); killing only the
    direct child would leak those processes beyond the run's timeout budget.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    if os.name == "posix":
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
    else:  # pragma: no cover - the host adapter is POSIX-only in V1
        proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
    else:  # pragma: no cover
        proc.kill()


def _run_harness_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_seconds: Optional[float],
) -> subprocess.CompletedProcess:
    """Run argv in its own process group and return a CompletedProcess.

    ``start_new_session=True`` makes the child a session/group leader so the
    entire tree can be reaped on timeout. On timeout the group is terminated
    and any partial output captured; ``subprocess.TimeoutExpired`` is raised to
    the caller with the captured output.
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        cwd=cwd,
        env=env,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(proc)
        try:
            stdout, stderr = proc.communicate()
        except Exception:
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout_seconds, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(args=argv, returncode=proc.returncode, stdout=stdout, stderr=stderr)


def run_harness_subprocess(tv: TestVersion, harness: Harness, model: Model, timeout_seconds: int = 30, workspace: Optional[Path | str] = None, *, workspace_prepared: bool = False) -> HarnessResult:
    """Execute via the declared adapter (argv, no shell, restricted env, cwd=workspace).

    Any preflight failure returns error='not-configured' without spawning.
    ``workspace_prepared=True`` means the source was already materialized into
    the workspace, so it is no longer required to be empty.
    """
    preflight_error = check_preflight(harness, model, tv, workspace=workspace, require_fresh_workspace=not workspace_prepared)
    if preflight_error is not None:
        return _not_configured(preflight_error)
    adapter = resolve_adapter(harness)
    assert adapter is not None
    policy, _ = resolve_permission_policy(tv.permission_profile)
    assert policy is not None
    ws = _resolve_lenient(Path(workspace))  # type: ignore[arg-type]
    argv = adapter.build_argv(tv, model, ws)
    env = adapter.build_env(policy, ws)
    start = time.monotonic()
    try:
        proc = _run_harness_process(argv, cwd=str(ws), env=env, timeout_seconds=timeout_seconds)
        return HarnessResult(exit_code=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "", elapsed_seconds=time.monotonic() - start, timed_out=False)
    except subprocess.TimeoutExpired as e:
        def _txt(v):
            if not v:
                return ""
            return v.decode(errors="replace") if isinstance(v, bytes) else str(v)
        return HarnessResult(exit_code=None, stdout=_txt(e.stdout), stderr=_txt(e.stderr), elapsed_seconds=time.monotonic() - start, timed_out=True, error="timeout")
    except FileNotFoundError as e:
        return _not_configured(f"{adapter.binary} binary not available: {e}", time.monotonic() - start)
    except Exception as e:
        return HarnessResult(exit_code=None, stdout="", stderr=str(e), elapsed_seconds=time.monotonic() - start, timed_out=False, error=str(e))



def _map_process_outcome(result: HarnessResult) -> ProcessOutcome:
    if result.timed_out:
        return ProcessOutcome.TIMEOUT
    if result.error is not None or result.exit_code is None:
        return ProcessOutcome.UNKNOWN
    return ProcessOutcome.SUCCESS if result.exit_code == 0 else ProcessOutcome.FAILURE


def _persist_evidence(run_id: int, attempt_number: int, result: HarnessResult, meta: dict) -> Optional[str]:
    """Write raw stdout/stderr and invocation metadata. Returns location or None.

    The destination is re-derived from the server-owned runs root and the
    resolved path must remain inside it: a symlinked ``run_id`` directory can
    never redirect evidence outside the evidence root.
    """
    try:
        if int(run_id) <= 0 or int(attempt_number) <= 0:
            return None
        root = _resolve_lenient(_runs_root())
        d = _evidence_dir_for_attempt(int(run_id), int(attempt_number))
        resolved = _resolve_lenient(d)
        if not _is_within(resolved, root):
            return None
        resolved.mkdir(parents=True, exist_ok=True)
        # Re-resolve after creation so a symlink swapped in mid-flight is caught.
        resolved = _resolve_lenient(d)
        if not _is_within(resolved, root):
            return None
        (resolved / "stdout.txt").write_text(result.stdout or "")
        (resolved / "stderr.txt").write_text(result.stderr or "")
        (resolved / "invocation.json").write_text(json.dumps(meta, indent=2, default=str))
        return str(resolved)
    except Exception:
        return None



# ---------------------------------------------------------------------------
# Service entry point
# ---------------------------------------------------------------------------

def _resolve_harness(session: Session, harness_id: Optional[int], is_demo: bool) -> Harness:
    if harness_id is not None:
        harness = session.get(Harness, harness_id)
        if harness is None:
            raise ValueError(f"harness {harness_id} not found")
        return harness
    # Auto-select only among same-provenance, runnable harnesses. A real run
    # must never be bound to a demo harness (and vice versa).
    for h in session.scalars(select(Harness).where(Harness.is_demo == is_demo).order_by(Harness.id)).all():  # noqa: E712
        if is_harness_runnable(h):
            return h
    raise ValueError("no harness available: no runnable adapter configured – evaluation cannot start")


def execute_run(
    session: Session,
    *,
    test_version_id: int,
    model_id: int,
    harness_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    requested_by: str = "operator",
    is_demo: bool = False,
    workspace: Optional[Path | str] = None,
) -> tuple[Run, Attempt, HarnessResult]:
    """Create a Run + Attempt and execute through the declared harness adapter.

    - Validates identities; refuses demo/real provenance mixing.
    - Idempotency: same key + same parameters returns the existing run; same
      key with different parameters is refused.
    - Requires a runnable adapter, a host-enforceable permission profile, and a
      genuinely isolated fresh workspace; otherwise records INFRASTRUCTURE_FAILURE.
    - Materializes the registered fixture/source exactly or refuses.
    - Persists raw evidence; seals the attempt; task/deliverable stay UNKNOWN.
    """
    tv = session.get(TestVersion, test_version_id)
    if tv is None:
        raise ValueError(f"test_version {test_version_id} not found")
    model = session.get(Model, model_id)
    if model is None:
        raise ValueError(f"model {model_id} not found")
    harness = _resolve_harness(session, harness_id, is_demo)

    for label, row in (("test version", tv), ("model", model), ("harness", harness)):
        if bool(row.is_demo) != bool(is_demo):
            raise ValueError(f"provenance mismatch: {label} {row.id} is_demo={row.is_demo} but run is_demo={is_demo}; demo and real evidence must not mix")

    if not tv.capability_version:
        raise ValueError(
            f"refusing execution: TestVersion {test_version_id} has capability_version NULL — "
            f"capability identity is UNKNOWN and must stay UNKNOWN; register a new version with an exact capability version"
        )
    capability = session.scalar(select(Capability).where(Capability.capability_key == tv.capability_key, Capability.version == tv.capability_version))
    if capability is None:
        raise ValueError(f"capability for test_version {test_version_id} not found (key={tv.capability_key} version={tv.capability_version})")

    def _existing_for_key(key: str) -> Optional[tuple[Run, Attempt, HarnessResult]]:
        existing = session.scalar(select(Run).where(Run.idempotency_key == key))
        if existing is None:
            return None
        if existing.test_version_id != tv.id or existing.model_id != model.id or (harness_id is not None and existing.harness_id != harness.id):
            raise ValueError(f"idempotency key reused with different parameters (existing run {existing.id}); refusing to alias a different evaluation")
        attempt = session.scalar(select(Attempt).where(Attempt.run_id == existing.id).order_by(Attempt.attempt_number.desc()))
        return existing, attempt, HarnessResult(exit_code=None, stdout="", stderr="duplicate", elapsed_seconds=0, timed_out=False, error="duplicate")  # type: ignore[return-value]

    if idempotency_key:
        dup = _existing_for_key(idempotency_key)
        if dup is not None:
            return dup

    now = datetime.now(timezone.utc)
    run = Run(
        test_version_id=tv.id,
        harness_id=harness.id,
        model_id=model.id,
        capability_id=capability.id,
        source_commit=tv.source_commit,
        source_fixture=tv.source_fixture_ref,
        permission_profile=tv.permission_profile,
        state=RunState.RUNNING,
        requested_at=now,
        started_at=now,
        is_demo=is_demo,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
    )
    session.add(run)
    try:
        # Persist the Run immediately (state=RUNNING) and end the write
        # transaction before the harness executes. Holding a SQLite write lock
        # for the whole (up to timeout) harness run would block every other
        # operator request; the Run is durably visible as RUNNING meanwhile.
        session.flush()
        session.commit()
    except IntegrityError:
        # Lost a race on the unique idempotency index: return the winner.
        session.rollback()
        if idempotency_key:
            dup = _existing_for_key(idempotency_key)
            if dup is not None:
                return dup
        raise

    run_id = run.id
    if workspace is not None:
        workspace_path = _resolve_lenient(Path(workspace))
    else:
        workspace_path = _resolve_lenient(_default_workspace_for_run(run_id))
    attempt_start = datetime.now(timezone.utc)

    source_state: Optional[dict] = None
    preflight_err = check_preflight(harness, model, tv, workspace=workspace_path)
    if preflight_err is None:
        source_state, prep_err = _prepare_run_workspace(workspace_path, tv)
        if prep_err is not None:
            preflight_err = prep_err

    if preflight_err is not None:
        result = _not_configured(preflight_err)
    else:
        result = run_harness_subprocess(tv, harness, model, timeout_seconds=tv.timeout_seconds or 60, workspace=workspace_path, workspace_prepared=True)
    attempt_end = datetime.now(timezone.utc)

    not_configured = result.error == NOT_CONFIGURED
    process_outcome = ProcessOutcome.UNKNOWN if not_configured else _map_process_outcome(result)

    permission_denied = False
    denial_evidence = None
    if not not_configured:
        combined = (result.stdout + " " + result.stderr).lower()
        if "denied" in combined and ("permission" in combined or "not in profile" in combined):
            permission_denied = True
            denial_evidence = (result.stderr or result.stdout)[:2000]

    try:
        argv = None if not_configured else ADAPTERS[resolve_adapter(harness).key].build_argv(tv, model, _resolve_lenient(workspace_path))  # type: ignore[union-attr]
    except Exception:
        argv = None
    meta = {
        "harness": harness.harness_key,
        "adapter": (resolve_adapter(harness).key if resolve_adapter(harness) else None),
        "model": model.model_key,
        "model_exact_identifier": model.exact_identifier,
        "test_version_id": tv.id,
        "definition_hash": tv.definition_hash,
        "capability": {"key": capability.capability_key, "version": capability.version},
        "permission_profile": tv.permission_profile,
        "argv": argv,
        "workspace": str(workspace_path),
        "source": source_state,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "error": result.error,
        "stderr_excerpt": (result.stderr or "")[:2000],
    }
    evidence_location = _persist_evidence(run_id, 1, result, meta)

    attempt = Attempt(
        run_id=run_id,
        attempt_number=1,
        started_at=attempt_start,
        finished_at=attempt_end,
        elapsed_seconds=(result.elapsed_seconds or None) if not_configured else result.elapsed_seconds,
        time_to_first_output_seconds=None,
        exit_code=result.exit_code,
        process_outcome=process_outcome,
        deliverable_outcome=DeliverableOutcome.UNKNOWN,
        task_outcome=TaskOutcome.UNKNOWN,
        repo_modification_outcome=RepoModificationOutcome.UNKNOWN,
        permission_denied=permission_denied,
        permission_denial_evidence=denial_evidence,
        timed_out=result.timed_out,
        cancelled=False,
        tokens_input=None,
        tokens_output=None,
        cost=None,
        cost_source=None,
        human_intervention=False,
        frontier_escalation=False,
        failure_primary=FailureClassification.INFRASTRUCTURE_FAILURE if not_configured else None,
        raw_evidence_location=evidence_location,
        artifact_refs=None,
        invocation_meta=json.dumps(meta, default=str),
        sealed_at=attempt_end,
        is_demo=is_demo,
    )
    session.add(attempt)
    run.finished_at = attempt_end
    run.state = RunState.INFRASTRUCTURE_FAILURE if not_configured else RunState.COMPLETED
    session.flush()

    audit = AuditEvent(
        action="run_execution",
        actor=requested_by,
        run_id=run_id,
        attempt_id=attempt.id,
        details=f"test_version={tv.id} model={model.id} harness={harness.id} exit={result.exit_code} process={process_outcome.value} workspace={workspace_path}",
        is_demo=is_demo,
    )
    session.add(audit)
    session.commit()
    return run, attempt, result
