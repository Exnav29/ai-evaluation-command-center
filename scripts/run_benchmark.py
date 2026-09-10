#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def command_output(args, cwd=ROOT) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def model_slug(model: str) -> str:
    value = model.split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")


def next_attempt(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    numbers = []
    for path in base.glob("attempt-*"):
        try:
            numbers.append(int(path.name.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return base / f"attempt-{max(numbers, default=0) + 1:03d}"


def validate_deliverable(text: str, config: dict | None) -> dict:
    if config is None:
        return {
            "status": "NOT_CHECKED",
            "reason": "No structural validator configured.",
            "character_count": len(text),
            "matched_groups": 0,
            "required_groups": 0,
        }

    min_chars = int(config.get("min_response_chars", 0))
    groups = config.get("required_term_groups", [])
    minimum_groups = int(config.get("minimum_groups_matched", len(groups)))

    lower = text.lower()
    matched = []
    missing = []

    for group in groups:
        terms = [str(term).lower() for term in group]
        if any(term in lower for term in terms):
            matched.append(group)
        else:
            missing.append(group)

    reasons = []
    if len(text.strip()) < min_chars:
        reasons.append(
            f"response too short ({len(text.strip())} < {min_chars} characters)"
        )
    if len(matched) < minimum_groups:
        reasons.append(
            f"only {len(matched)} of {len(groups)} required content groups matched; "
            f"minimum is {minimum_groups}"
        )

    return {
        "status": "MISSING" if reasons else "PRESENT",
        "reason": "; ".join(reasons) if reasons else "Structural deliverable checks passed.",
        "character_count": len(text),
        "matched_groups": len(matched),
        "required_groups": len(groups),
        "minimum_groups_matched": minimum_groups,
        "missing_groups": missing,
    }


parser = argparse.ArgumentParser(
    description="Run a reproducible AI Evaluation Command Center benchmark."
)
parser.add_argument("--model", required=True)
parser.add_argument(
    "--benchmark",
    default="phase2-command-center-planning-v1",
)
parser.add_argument(
    "--prompt",
    default="prompts/phase2-command-center-planning-v1.txt",
)
parser.add_argument(
    "--title",
    default="phase2-command-center-planning",
)
parser.add_argument(
    "--source-ref",
    default="HEAD",
    help="Git commit/ref exposed to the model. Pin this for fair comparisons.",
)
parser.add_argument(
    "--validator",
    default=None,
    help="Structural deliverable validator JSON. Defaults to validators/<benchmark>.json if present.",
)
args = parser.parse_args()

before_status = command_output(["git", "status", "--porcelain"])
if before_status:
    print("ERROR: Evaluator repository is not clean.")
    print(before_status)
    sys.exit(2)

subject_sha = command_output(["git", "rev-parse", args.source_ref])
if not re.fullmatch(r"[0-9a-f]{40}", subject_sha):
    print(f"ERROR: Could not resolve source ref: {args.source_ref}")
    sys.exit(2)

evaluator_sha = command_output(["git", "rev-parse", "HEAD"])
slug = model_slug(args.model)
base_dir = ROOT / "runs" / "evaluations" / args.benchmark / slug
run_dir = next_attempt(base_dir)
run_dir.mkdir(parents=True)

response_path = run_dir / "response.txt"
manifest_path = run_dir / "manifest.json"
elapsed_path = run_dir / "elapsed-seconds.txt"
first_output_path = run_dir / "first-process-output-seconds.txt"
process_exit_path = run_dir / "process-exit-code.txt"
runner_exit_path = run_dir / "runner-exit-code.txt"

validator_path = (
    ROOT / args.validator
    if args.validator
    else ROOT / "validators" / f"{args.benchmark}.json"
)
validator_config = None
if validator_path.exists():
    validator_config = json.loads(validator_path.read_text())

temp_parent = None
subject_dir = ROOT
runner_exit_code = 2

try:
    if subject_sha != evaluator_sha:
        temp_parent = Path(tempfile.mkdtemp(prefix="aecc-benchmark-"))
        subject_dir = temp_parent / "subject"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(subject_dir), subject_sha],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    prompt_path = subject_dir / args.prompt
    if not prompt_path.exists():
        print(f"ERROR: Prompt file not found in subject snapshot: {args.prompt}")
        sys.exit(2)

    tracked_inputs = [
        "docs/COMMAND_CENTER_V1_SPEC.md",
        "docs/PLANNING_RUBRIC_V1.md",
        args.prompt,
        "skills-lock.json",
        "opencode.jsonc",
    ]
    input_hashes = {}
    for relative in tracked_inputs:
        path = subject_dir / relative
        input_hashes[relative] = sha256_file(path) if path.exists() else None

    prompt = prompt_path.read_text()
    opencode_version = command_output(["opencode", "--version"])

    cmd = [
        "opencode",
        "run",
        "--dir",
        str(subject_dir),
        "--model",
        args.model,
        "--title",
        args.title,
        prompt,
    ]

    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    first_process_output_seconds = None

    print(f"Benchmark:     {args.benchmark}")
    print(f"Model:         {args.model}")
    print(f"Subject SHA:   {subject_sha}")
    print(f"Evaluator SHA: {evaluator_sha}")
    print(f"Run dir:       {run_dir.relative_to(ROOT)}")
    print()
    print("=== MODEL OUTPUT ===")

    with response_path.open("w") as output:
        process = subprocess.Popen(
            cmd,
            cwd=subject_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None

        for line in process.stdout:
            now = time.perf_counter()
            if first_process_output_seconds is None:
                first_process_output_seconds = now - start
            print(line, end="", flush=True)
            output.write(line)
            output.flush()

        process_exit_code = process.wait()

    elapsed = time.perf_counter() - start
    finished_at = datetime.now(timezone.utc)
    subject_status_after = command_output(
        ["git", "status", "--porcelain"], cwd=subject_dir
    )

    response_text = response_path.read_text()
    deliverable = validate_deliverable(response_text, validator_config)

    if process_exit_code != 0:
        process_status = "FAILED"
        benchmark_status = "PROCESS_FAILURE"
        runner_exit_code = process_exit_code
    elif deliverable["status"] == "MISSING":
        process_status = "SUCCESS"
        benchmark_status = "TASK_FAILURE"
        runner_exit_code = 3
    elif deliverable["status"] == "PRESENT":
        process_status = "SUCCESS"
        benchmark_status = "READY_FOR_SCORING"
        runner_exit_code = 0
    else:
        process_status = "SUCCESS"
        benchmark_status = "REQUIRES_REVIEW"
        runner_exit_code = 0

    permission_denial_detected = (
        "permission requested:" in response_text.lower()
        and (
            "auto-rejecting" in response_text.lower()
            or "rejected permission" in response_text.lower()
        )
    )

    elapsed_path.write_text(f"{elapsed:.3f}\n")
    process_exit_path.write_text(f"{process_exit_code}\n")
    runner_exit_path.write_text(f"{runner_exit_code}\n")
    if first_process_output_seconds is None:
        first_output_path.write_text("UNKNOWN\n")
    else:
        first_output_path.write_text(f"{first_process_output_seconds:.3f}\n")

    manifest = {
        "benchmark": args.benchmark,
        "harness": "opencode",
        "model": args.model,
        "model_slug": slug,
        "prompt_file": args.prompt,
        "subject_git_ref_requested": args.source_ref,
        "subject_git_head": subject_sha,
        "evaluator_git_head": evaluator_sha,
        "validator_file": (
            str(validator_path.relative_to(ROOT))
            if validator_path.exists()
            else None
        ),
        "validator_sha256": (
            sha256_file(validator_path) if validator_path.exists() else None
        ),
        "git_clean_before": True,
        "repository_modified_by_run": bool(subject_status_after),
        "repository_status_after": subject_status_after or None,
        "opencode_version": opencode_version,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "first_process_output_seconds": (
            round(first_process_output_seconds, 3)
            if first_process_output_seconds is not None
            else None
        ),
        "process_exit_code": process_exit_code,
        "process_status": process_status,
        "deliverable_status": deliverable,
        "benchmark_status": benchmark_status,
        "runner_exit_code": runner_exit_code,
        "permission_denial_detected": permission_denial_detected,
        "input_sha256": input_hashes,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print()
    print("=== BENCHMARK RESULT ===")
    print(f"Elapsed seconds:       {elapsed:.3f}")
    print(
        "First process output:  "
        + (
            f"{first_process_output_seconds:.3f}s"
            if first_process_output_seconds is not None
            else "UNKNOWN"
        )
    )
    print(f"Process exit code:     {process_exit_code}")
    print(f"Process status:        {process_status}")
    print(f"Deliverable status:    {deliverable['status']}")
    print(f"Benchmark status:      {benchmark_status}")
    print(f"Permission denial:     {'YES' if permission_denial_detected else 'NO'}")
    print(f"Repository modified:  {'YES' if subject_status_after else 'NO'}")
    print(f"Runner exit code:      {runner_exit_code}")
    print(f"Evidence directory:    {run_dir.relative_to(ROOT)}")

finally:
    if temp_parent is not None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(subject_dir)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        shutil.rmtree(temp_parent, ignore_errors=True)

sys.exit(runner_exit_code)
