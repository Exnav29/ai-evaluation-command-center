#!/usr/bin/env python3
"""Contained implementation benchmark runner for Phase 3."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = "phase3-foundation-implementation-v1"
FREEZE_PATH = ROOT / "benchmarks" / BENCHMARK / "FREEZE.json"
DEFAULT_IMAGE = "localhost/aecc-phase3-runner:v1"
DEFAULT_NETWORK = "aecc-restricted"
DEFAULT_PROXY = "aecc-egress-proxy"


def command_output(args: list[str], cwd: Path = ROOT) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_slug(model: str) -> str:
    value = model.split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")


def next_attempt(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    numbers: list[int] = []
    for path in base.glob("attempt-*"):
        try:
            numbers.append(int(path.name.split("-", 1)[1]))
        except (IndexError, ValueError):
            pass
    return base / f"attempt-{max(numbers, default=0) + 1:03d}"


def require_clean_evaluator() -> None:
    status = command_output(["git", "status", "--porcelain"])
    if status:
        print("ERROR: Evaluator repository is not clean.")
        print(status)
        sys.exit(2)


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        print(f"ERROR: Required command not found: {name}")
        sys.exit(2)
    return path


def require_podman_object(kind: str, name: str) -> None:
    if kind == "network":
        result = subprocess.run(
            ["podman", "network", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        result = subprocess.run(
            ["podman", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if result.returncode != 0:
        print(f"ERROR: Required Podman {kind} is unavailable: {name}")
        sys.exit(2)


def require_image(image: str) -> None:
    result = subprocess.run(
        ["podman", "image", "exists", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        print(f"ERROR: Required benchmark image is unavailable: {image}")
        sys.exit(2)


def stream_process(cmd: list[str], output_path: Path, timeout_seconds: int, timeout_cleanup=None):
    started = time.perf_counter()
    first_output = None
    timed_out = False

    with output_path.open("wb") as out:
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)

        while True:
            elapsed = time.perf_counter() - started
            if elapsed >= timeout_seconds:
                timed_out = True
                if timeout_cleanup is not None:
                    try:
                        timeout_cleanup()
                    except Exception:
                        pass
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break

            events = selector.select(timeout=min(0.25, timeout_seconds - elapsed))
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if chunk:
                    if first_output is None:
                        first_output = time.perf_counter() - started
                    out.write(chunk)
                    out.flush()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()

            if process.poll() is not None:
                while True:
                    try:
                        chunk = os.read(process.stdout.fileno(), 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    if first_output is None:
                        first_output = time.perf_counter() - started
                    out.write(chunk)
                    sys.stdout.buffer.write(chunk)
                out.flush()
                sys.stdout.buffer.flush()
                break

        selector.close()
        rc = process.poll()
        if rc is None:
            rc = process.wait()

    elapsed = time.perf_counter() - started
    return int(rc), elapsed, first_output, timed_out


def archive_workspace(workspace: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(workspace, arcname="workspace", recursive=True)


def changed_evidence(workspace: Path, run_dir: Path) -> dict:
    status = command_output(["git", "status", "--porcelain=v1"], cwd=workspace)
    diff_binary = command_output(["git", "diff", "--binary", "HEAD"], cwd=workspace)
    tracked_changed = command_output(["git", "diff", "--name-only", "HEAD"], cwd=workspace).splitlines()
    untracked = command_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace).splitlines()
    changed = sorted({p for p in tracked_changed + untracked if p})

    (run_dir / "git-status-after.txt").write_text(status + ("\n" if status else ""), encoding="utf-8")
    (run_dir / "git-diff-binary.patch").write_text(diff_binary + ("\n" if diff_binary else ""), encoding="utf-8")
    (run_dir / "changed-files.txt").write_text("\n".join(changed) + ("\n" if changed else ""), encoding="utf-8")
    (run_dir / "untracked-files.txt").write_text("\n".join(untracked) + ("\n" if untracked else ""), encoding="utf-8")

    return {
        "git_status_after": status or None,
        "tracked_changed_files": tracked_changed,
        "untracked_files": untracked,
        "changed_files": changed,
    }


def structural_validation(workspace: Path, validator: dict, changed_files: list[str]) -> dict:
    groups = []
    all_present = True
    for group in validator.get("required_path_groups", []):
        matches: list[str] = []
        for pattern in group.get("patterns", []):
            for match in glob.glob(str(workspace / pattern), recursive=True):
                p = Path(match)
                if p.is_file():
                    matches.append(str(p.relative_to(workspace)))
        matches = sorted(set(matches))
        present = bool(matches)
        all_present = all_present and present
        groups.append({"name": group.get("name"), "present": present, "matches": matches})

    forbidden = set(validator.get("forbidden_changed_paths", []))
    forbidden_changed = sorted(forbidden.intersection(changed_files))

    return {
        "required_path_groups": groups,
        "all_required_path_groups_present": all_present,
        "forbidden_changed_paths": forbidden_changed,
        "forbidden_paths_unchanged": not forbidden_changed,
        "repository_changed": bool(changed_files),
    }


def run_independent_verification(workspace: Path, verification_parent: Path, run_dir: Path, image: str, timeout_seconds: int):
    verify_dir = verification_parent / "verification-workspace"
    shutil.copytree(workspace, verify_dir, symlinks=True)
    output_path = run_dir / "independent-pytest.txt"
    cmd = [
        "podman", "run", "--rm", "--network=none",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=256", "--memory=1g", "--cpus=1",
        "-v", f"{verify_dir}:/workspace:rw,Z", "-w", "/workspace",
        image, "python", "-m", "pytest", "-q",
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout_seconds)
        output_path.write_bytes(result.stdout)
        return result.returncode, False
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
        if exc.stderr:
            data += exc.stderr
        data += b"\nVERIFICATION TIMEOUT\n"
        output_path.write_bytes(data)
        return 124, True


def proxy_logs(path: Path, proxy: str) -> None:
    result = subprocess.run(["podman", "logs", proxy], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    path.write_bytes(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen Phase 3 implementation benchmark in containment.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--network", default=DEFAULT_NETWORK)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    args = parser.parse_args()

    require_clean_evaluator()
    require_command("git")
    require_command("podman")
    opencode_path = Path(require_command("opencode"))

    if not FREEZE_PATH.exists():
        print(f"ERROR: Freeze manifest not found: {FREEZE_PATH}")
        return 2

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    source_sha = freeze["subject_source_commit"]
    timeout_seconds = int(freeze["timeout_seconds"])
    validator_rel = freeze["validator_contract"]
    prompt_rel = freeze["prompt"]

    evaluator_sha = command_output(["git", "rev-parse", "HEAD"])
    resolved_source = command_output(["git", "rev-parse", source_sha])
    if resolved_source != source_sha:
        print(f"ERROR: Frozen source commit cannot be resolved exactly: {source_sha}")
        return 2

    require_image(args.image)
    require_podman_object("network", args.network)
    require_podman_object("container", args.proxy)

    rootless = command_output(["podman", "info", "--format", "{{.Host.Security.Rootless}}"])
    if rootless.strip().lower() != "true":
        print("ERROR: Podman is not running rootless.")
        return 2

    proxy_running = command_output(["podman", "inspect", "-f", "{{.State.Running}}", args.proxy])
    if proxy_running.strip().lower() != "true":
        print(f"ERROR: Egress proxy is not running: {args.proxy}")
        return 2

    auth_source = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if not auth_source.exists():
        print(f"ERROR: OpenCode Zen auth file not found: {auth_source}")
        return 2

    npm_prefix = opencode_path.parent.parent
    if not npm_prefix.exists():
        print(f"ERROR: Could not derive OpenCode runtime prefix: {npm_prefix}")
        return 2

    slug = model_slug(args.model)
    base_dir = ROOT / "runs" / "evaluations" / BENCHMARK / slug
    run_dir = next_attempt(base_dir)
    run_dir.mkdir(parents=True)

    temp_parent = Path(tempfile.mkdtemp(prefix="aecc-phase3-"))
    workspace = temp_parent / "subject"
    auth_data = temp_parent / "opencode-data"
    auth_dir = auth_data / "opencode"
    auth_dir.mkdir(parents=True)
    shutil.copy2(auth_source, auth_dir / "auth.json")
    os.chmod(auth_dir / "auth.json", 0o600)

    model_output = run_dir / "response.txt"
    archive_path = run_dir / "final-workspace.tar.gz"
    manifest_path = run_dir / "manifest.json"
    container_name = f"aecc-{slug[:32]}-{run_dir.name}"

    try:
        clone = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(workspace)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if clone.returncode != 0:
            print("ERROR: Could not create disposable subject clone.")
            print(clone.stdout)
            return 2

        checkout = subprocess.run(
            ["git", "checkout", "--quiet", "--detach", source_sha],
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if checkout.returncode != 0:
            print("ERROR: Could not check out frozen source commit.")
            print(checkout.stdout)
            return 2

        prompt_path = workspace / prompt_rel
        validator_path = workspace / validator_rel
        if not prompt_path.exists() or not validator_path.exists():
            print("ERROR: Frozen prompt or validator is missing from subject snapshot.")
            return 2

        prompt = prompt_path.read_text(encoding="utf-8")
        validator = json.loads(validator_path.read_text(encoding="utf-8"))
        opencode_version = command_output(["opencode", "--version"])
        image_id = command_output(["podman", "image", "inspect", args.image, "-f", "{{.Id}}"])
        started_at = datetime.now(timezone.utc)
        proxy_logs(run_dir / "proxy-log-before.txt", args.proxy)

        cmd = [
            "podman", "run", "--name", container_name, "--rm",
            "--network", args.network,
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=512", "--memory=2g", "--cpus=2",
            "-e", "HOME=/tmp/aecc-home",
            "-e", "XDG_DATA_HOME=/tmp/aecc-home/.local/share",
            "-e", f"HTTP_PROXY=http://{args.proxy}:3128",
            "-e", f"HTTPS_PROXY=http://{args.proxy}:3128",
            "-e", f"http_proxy=http://{args.proxy}:3128",
            "-e", f"https_proxy=http://{args.proxy}:3128",
            "-e", "NO_PROXY=localhost,127.0.0.1",
            "-e", "no_proxy=localhost,127.0.0.1",
            "-v", f"{auth_data}:/tmp/aecc-home/.local/share:rw,Z",
            "-v", f"{npm_prefix}:/opt/opencode:ro,Z",
            "-v", f"{workspace}:/workspace:rw,Z",
            "-w", "/workspace",
            args.image,
            "opencode", "run", "--auto", "--dir", "/workspace",
            "--model", args.model,
            "--title", f"{BENCHMARK}-{slug}",
            prompt,
        ]

        print(f"Benchmark:      {BENCHMARK}")
        print(f"Model:          {args.model}")
        print(f"Subject SHA:    {source_sha}")
        print(f"Evaluator SHA:  {evaluator_sha}")
        print(f"Image:          {args.image}")
        print(f"Image ID:       {image_id}")
        print(f"Network:        {args.network}")
        print(f"Egress proxy:   {args.proxy}")
        print(f"Run dir:        {run_dir.relative_to(ROOT)}")
        print()
        print("=== MODEL OUTPUT ===")

        def cleanup_container():
            subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        process_exit, elapsed, first_output, timed_out = stream_process(
            cmd, model_output, timeout_seconds=timeout_seconds, timeout_cleanup=cleanup_container
        )
        finished_at = datetime.now(timezone.utc)
        proxy_logs(run_dir / "proxy-log-after.txt", args.proxy)

        changed = changed_evidence(workspace, run_dir)
        structural = structural_validation(workspace, validator, changed["changed_files"])

        archive_workspace(workspace, archive_path)
        archive_sha = sha256_file(archive_path)

        verify_timeout = int(validator.get("verification_timeout_seconds", 180))
        verification_exit, verification_timed_out = run_independent_verification(
            workspace, temp_parent, run_dir, args.image, verify_timeout
        )

        response_text = model_output.read_text(encoding="utf-8", errors="replace")
        permission_denial = bool(re.search(r"(permission.*(denied|rejected)|auto-rejecting|forbidden)", response_text, re.IGNORECASE))

        if timed_out:
            process_status = "TIMEOUT"
        elif process_exit == 0:
            process_status = "SUCCESS"
        else:
            process_status = "FAILURE"

        deliverable_present = structural["repository_changed"] and structural["all_required_path_groups_present"]
        if not deliverable_present:
            deliverable_status = "MISSING"
        elif not structural["forbidden_paths_unchanged"]:
            deliverable_status = "INVALID"
        else:
            deliverable_status = "PRESENT"

        verification_status = "TIMEOUT" if verification_timed_out else ("PASS" if verification_exit == 0 else "FAIL")
        task_status = (
            "SUCCESS_CANDIDATE_READY_FOR_SCORING"
            if deliverable_status == "PRESENT" and verification_exit == 0
            else "TASK_FAILURE"
        )

        manifest = {
            "benchmark": BENCHMARK,
            "capability": freeze.get("capability"),
            "harness": "opencode",
            "harness_version": opencode_version,
            "model": args.model,
            "model_slug": slug,
            "subject_git_head": source_sha,
            "evaluator_git_head": evaluator_sha,
            "benchmark_image": args.image,
            "benchmark_image_id": image_id,
            "containment": {
                "rootless_podman": True,
                "network": args.network,
                "egress_proxy": args.proxy,
                "direct_internet": "BLOCKED_BY_INTERNAL_NETWORK",
                "approved_provider_egress": "opencode.ai:443 via proxy",
                "host_home_mounted": False,
                "product_studio_mounted": False,
                "container_engine_socket_mounted": False
            },
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(elapsed, 3),
            "first_process_output_seconds": round(first_output, 3) if first_output is not None else None,
            "process_exit_code": process_exit,
            "process_status": process_status,
            "deliverable_status": deliverable_status,
            "task_status": task_status,
            "permission_denial_detected": permission_denial,
            "human_intervention": False,
            "repository_modified_by_run": changed["git_status_after"] is not None,
            "changed_files": changed["changed_files"],
            "untracked_files": changed["untracked_files"],
            "structural_validation": structural,
            "independent_verification": {
                "command": "python -m pytest -q",
                "exit_code": verification_exit,
                "status": verification_status,
                "timeout_seconds": verify_timeout
            },
            "evidence": {
                "model_response": "response.txt",
                "git_status_after": "git-status-after.txt",
                "git_diff_binary": "git-diff-binary.patch",
                "changed_file_list": "changed-files.txt",
                "untracked_file_list": "untracked-files.txt",
                "final_workspace_archive": "final-workspace.tar.gz",
                "final_workspace_archive_sha256": archive_sha,
                "verification_stdout_stderr": "independent-pytest.txt",
                "proxy_log_before": "proxy-log-before.txt",
                "proxy_log_after": "proxy-log-after.txt"
            },
            "score": None,
            "rubric_version": "docs/IMPLEMENTATION_RUBRIC_V1.md"
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        (run_dir / "elapsed-seconds.txt").write_text(f"{elapsed:.3f}\n")
        (run_dir / "first-process-output-seconds.txt").write_text("UNKNOWN\n" if first_output is None else f"{first_output:.3f}\n")
        (run_dir / "process-exit-code.txt").write_text(f"{process_exit}\n")
        (run_dir / "verification-exit-code.txt").write_text(f"{verification_exit}\n")
        (run_dir / "workspace-sha256.txt").write_text(f"{archive_sha}\n")

        print()
        print("=== IMPLEMENTATION BENCHMARK RESULT ===")
        print(f"Elapsed seconds:       {elapsed:.3f}")
        print("First process output:  " + (f"{first_output:.3f}s" if first_output is not None else "UNKNOWN"))
        print(f"Process exit code:     {process_exit}")
        print(f"Process status:        {process_status}")
        print(f"Deliverable status:    {deliverable_status}")
        print(f"Independent pytest:    {verification_status} (exit {verification_exit})")
        print(f"Task status:           {task_status}")
        print(f"Forbidden files changed: {'YES' if structural['forbidden_changed_paths'] else 'NO'}")
        print(f"Changed files:         {len(changed['changed_files'])}")
        print(f"Workspace SHA-256:     {archive_sha}")
        print(f"Evidence directory:    {run_dir.relative_to(ROOT)}")

        return 0 if task_status == "SUCCESS_CANDIDATE_READY_FOR_SCORING" else 3

    finally:
        subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(temp_parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
