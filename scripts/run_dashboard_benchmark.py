#!/usr/bin/env python3
"""Contained runner for Product Phase 3 Operator Dashboard V1."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import run_implementation_benchmark as base

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = "phase3-operator-dashboard-v1"
FREEZE_PATH = ROOT / "benchmarks" / BENCHMARK / "FREEZE.json"
DEFAULT_IMAGE = "localhost/aecc-dashboard-runner:v1"
DEFAULT_NETWORK = "aecc-restricted"
DEFAULT_PROXY = "aecc-egress-proxy"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def observation_from_response(text: str) -> dict:
    lines = text.splitlines()
    skill_lines = [ln for ln in lines if re.search(r"\bskill\b", ln, re.I)]
    subagent_lines = [ln for ln in lines if re.search(r"\b(subagent|task)\b", ln, re.I)]
    failed_tool_lines = [ln for ln in lines if ln.lstrip().startswith("✗") or re.search(r"tool call.*(failed|denied|rejected)", ln, re.I)]
    denial_re = re.compile(
        r"permission.*(denied|rejected)|auto-rejecting|forbidden|"
        r"specified a rule which prevents you|\"action\"\s*:\s*\"deny\"",
        re.I,
    )
    denial_lines = [ln for ln in lines if denial_re.search(ln)]
    return {
        "skill_related_lines": skill_lines,
        "skill_related_line_count": len(skill_lines),
        "subagent_or_task_related_lines": subagent_lines,
        "subagent_or_task_related_line_count": len(subagent_lines),
        "failed_tool_lines": failed_tool_lines,
        "failed_tool_line_count": len(failed_tool_lines),
        "permission_denial_lines": denial_lines,
        "permission_denial_detected": bool(denial_lines),
        "note": "Raw response is authoritative; parsed counts are observational and may be UNKNOWN/partial depending on harness output.",
    }


def forbidden_glob_hits(changed_files: list[str], patterns: list[str]) -> list[str]:
    hits: set[str] = set()
    for path in changed_files:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                hits.add(path)
    return sorted(hits)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen Phase 3 dashboard benchmark in containment.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--network", default=DEFAULT_NETWORK)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    args = parser.parse_args()

    base.require_clean_evaluator()
    base.require_command("git")
    base.require_command("podman")
    opencode_path = Path(base.require_command("opencode"))

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if args.model not in freeze["competitors"]:
        print(f"ERROR: Model is not a frozen competitor: {args.model}")
        return 2

    source_sha = freeze["subject_source_commit"]
    timeout_seconds = int(freeze["timeout_seconds"])
    evaluator_sha = base.command_output(["git", "rev-parse", "HEAD"])
    if base.command_output(["git", "rev-parse", source_sha]) != source_sha:
        print("ERROR: Frozen subject commit cannot be resolved exactly.")
        return 2

    base.require_image(args.image)
    base.require_podman_object("network", args.network)
    base.require_podman_object("container", args.proxy)
    if base.command_output(["podman", "info", "--format", "{{.Host.Security.Rootless}}" ]).lower() != "true":
        print("ERROR: Podman is not rootless.")
        return 2
    if base.command_output(["podman", "inspect", "-f", "{{.State.Running}}", args.proxy]).lower() != "true":
        print("ERROR: Egress proxy is not running.")
        return 2

    auth_source = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if not auth_source.exists():
        print("ERROR: OpenCode Zen auth file not found.")
        return 2
    npm_prefix = opencode_path.parent.parent

    slug = base.model_slug(args.model)
    run_dir = base.next_attempt(ROOT / "runs" / "evaluations" / BENCHMARK / slug)
    run_dir.mkdir(parents=True)
    temp_parent = Path(tempfile.mkdtemp(prefix="aecc-dashboard-"))
    workspace = temp_parent / "subject"
    auth_data = temp_parent / "opencode-data"
    (auth_data / "opencode").mkdir(parents=True)
    shutil.copy2(auth_source, auth_data / "opencode" / "auth.json")
    os.chmod(auth_data / "opencode" / "auth.json", 0o600)

    output_path = run_dir / "response.txt"
    archive_path = run_dir / "final-workspace.tar.gz"
    container_name = f"aecc-dash-{slug[:28]}-{run_dir.name}"

    try:
        clone = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(workspace)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if clone.returncode:
            print(clone.stdout)
            return 2
        checkout = subprocess.run(["git", "checkout", "--quiet", "--detach", source_sha], cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if checkout.returncode:
            print(checkout.stdout)
            return 2

        prompt = (workspace / freeze["prompt"]).read_text(encoding="utf-8")
        validator = json.loads((workspace / freeze["validator_contract"]).read_text(encoding="utf-8"))
        opencode_version = base.command_output(["opencode", "--version"])
        image_id = base.command_output(["podman", "image", "inspect", args.image, "-f", "{{.Id}}"])
        runtime_config = json.dumps({
            "model": args.model,
            "small_model": args.model,
            "share": "disabled",
            "subagent_depth": 1,
            "agents": {
                "build": {"model": args.model},
                "general": {"model": args.model},
                "explore": {"model": args.model}
            }
        })

        started_at = datetime.now(timezone.utc)
        base.proxy_logs(run_dir / "proxy-log-before.txt", args.proxy)
        cmd = [
            "podman", "run", "--name", container_name, "--rm",
            "--network", args.network,
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=512", "--memory=2g", "--cpus=2",
            "-e", "HOME=/tmp/aecc-home",
            "-e", "XDG_DATA_HOME=/tmp/aecc-home/.local/share",
            "-e", f"OPENCODE_CONFIG_CONTENT={runtime_config}",
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
        print(f"Run dir:        {run_dir.relative_to(ROOT)}")
        print("Effective main model:  " + args.model)
        print("Effective small model: " + args.model)
        print("\n=== MODEL OUTPUT ===")

        def cleanup():
            subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        process_exit, elapsed, first_output, timed_out = base.stream_process(cmd, output_path, timeout_seconds, cleanup)
        finished_at = datetime.now(timezone.utc)
        base.proxy_logs(run_dir / "proxy-log-after.txt", args.proxy)

        changed = base.changed_evidence(workspace, run_dir)
        structural = base.structural_validation(workspace, validator, changed["changed_files"])
        glob_hits = forbidden_glob_hits(changed["changed_files"], validator.get("forbidden_changed_globs", []))
        structural["forbidden_glob_hits"] = glob_hits
        structural["forbidden_paths_unchanged"] = structural["forbidden_paths_unchanged"] and not glob_hits

        base.archive_workspace(workspace, archive_path)
        archive_sha = sha256_file(archive_path)
        verify_timeout = int(validator.get("verification_timeout_seconds", 240))
        verification_exit, verification_timed_out = base.run_independent_verification(workspace, temp_parent, run_dir, args.image, verify_timeout)

        response_text = output_path.read_text(encoding="utf-8", errors="replace")
        observation = observation_from_response(response_text)
        (run_dir / "tool-skill-subagent-observation.json").write_text(json.dumps(observation, indent=2) + "\n", encoding="utf-8")

        process_status = "TIMEOUT" if timed_out else ("SUCCESS" if process_exit == 0 else "FAILURE")
        deliverable_present = structural["repository_changed"] and structural["all_required_path_groups_present"]
        deliverable_status = "MISSING" if not deliverable_present else ("INVALID" if not structural["forbidden_paths_unchanged"] else "PRESENT")
        verification_status = "TIMEOUT" if verification_timed_out else ("PASS" if verification_exit == 0 else "FAIL")
        task_status = "SUCCESS_CANDIDATE_READY_FOR_SCORING" if deliverable_status == "PRESENT" and verification_exit == 0 else "TASK_FAILURE"

        manifest = {
            "benchmark": BENCHMARK,
            "capability": freeze["capability"],
            "harness": "opencode",
            "harness_version": opencode_version,
            "model": args.model,
            "effective_main_model": args.model,
            "effective_small_model": args.model,
            "single_model_attribution_runtime_forced": True,
            "subject_git_head": source_sha,
            "evaluator_git_head": evaluator_sha,
            "benchmark_image": args.image,
            "benchmark_image_id": image_id,
            "containment": {
                "rootless_podman": True,
                "network": args.network,
                "egress_proxy": args.proxy,
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
            "permission_denial_detected": observation["permission_denial_detected"],
            "human_intervention": False,
            "tool_skill_subagent_observation": observation,
            "changed_files": changed["changed_files"],
            "untracked_files": changed["untracked_files"],
            "structural_validation": structural,
            "independent_verification": {"command": "python -m pytest -q", "exit_code": verification_exit, "status": verification_status},
            "telemetry": {"tokens": "UNKNOWN_UNLESS_PROVIDER_EVIDENCE_ADDED", "actual_cost": "UNKNOWN_UNLESS_PROVIDER_EVIDENCE_ADDED"},
            "evidence": {
                "model_response": "response.txt",
                "git_status_after": "git-status-after.txt",
                "git_diff_binary": "git-diff-binary.patch",
                "changed_file_list": "changed-files.txt",
                "untracked_file_list": "untracked-files.txt",
                "final_workspace_archive": "final-workspace.tar.gz",
                "final_workspace_archive_sha256": archive_sha,
                "verification_stdout_stderr": "independent-pytest.txt",
                "tool_skill_subagent_observation": "tool-skill-subagent-observation.json",
                "proxy_log_before": "proxy-log-before.txt",
                "proxy_log_after": "proxy-log-after.txt"
            },
            "score": None,
            "rubric_version": freeze["rubric"]
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (run_dir / "workspace-sha256.txt").write_text(archive_sha + "\n", encoding="utf-8")

        print("\n=== DASHBOARD BENCHMARK RESULT ===")
        print(f"Elapsed seconds:       {elapsed:.3f}")
        print("First process output:  " + (f"{first_output:.3f}s" if first_output is not None else "UNKNOWN"))
        print(f"Process exit code:     {process_exit}")
        print(f"Process status:        {process_status}")
        print(f"Deliverable status:    {deliverable_status}")
        print(f"Independent pytest:    {verification_status} (exit {verification_exit})")
        print(f"Task status:           {task_status}")
        print(f"Permission denial:     {observation['permission_denial_detected']}")
        print(f"Skill-related lines:   {observation['skill_related_line_count']}")
        print(f"Subagent/task lines:   {observation['subagent_or_task_related_line_count']}")
        print(f"Failed tool lines:     {observation['failed_tool_line_count']}")
        print(f"Forbidden changes:     {'YES' if not structural['forbidden_paths_unchanged'] else 'NO'}")
        print(f"Changed files:         {len(changed['changed_files'])}")
        print(f"Workspace SHA-256:     {archive_sha}")
        print(f"Evidence directory:    {run_dir.relative_to(ROOT)}")
        return 0 if task_status == "SUCCESS_CANDIDATE_READY_FOR_SCORING" else 3
    finally:
        subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(temp_parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
