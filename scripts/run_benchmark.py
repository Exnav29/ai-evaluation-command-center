#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def command_output(args):
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def model_slug(model):
    value = model.split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")


def next_attempt(base):
    base.mkdir(parents=True, exist_ok=True)
    existing = []

    for path in base.glob("attempt-*"):
        try:
            existing.append(int(path.name.split("-")[1]))
        except (IndexError, ValueError):
            pass

    number = max(existing, default=0) + 1
    return base / f"attempt-{number:03d}"


parser = argparse.ArgumentParser(
    description="Run a reproducible AI Evaluation Command Center benchmark."
)

parser.add_argument(
    "--model",
    required=True,
    help="Exact OpenCode model ID, e.g. opencode/mimo-v2.5-free",
)

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

args = parser.parse_args()

# Benchmark execution requires a clean tracked repository.
before_status = command_output(["git", "status", "--porcelain"])

if before_status:
    print("ERROR: Repository is not clean.")
    print("Commit or discard tracked/untracked changes before benchmarking.")
    print()
    print(before_status)
    sys.exit(2)

prompt_path = ROOT / args.prompt

if not prompt_path.exists():
    print(f"ERROR: Prompt file not found: {prompt_path}")
    sys.exit(2)

slug = model_slug(args.model)
base_dir = ROOT / "runs" / "evaluations" / args.benchmark / slug
run_dir = next_attempt(base_dir)
run_dir.mkdir(parents=True)

response_path = run_dir / "response.txt"
manifest_path = run_dir / "manifest.json"
elapsed_path = run_dir / "elapsed-seconds.txt"
first_output_path = run_dir / "first-output-seconds.txt"
exit_path = run_dir / "exit-code.txt"

tracked_inputs = [
    "docs/COMMAND_CENTER_V1_SPEC.md",
    "docs/PLANNING_RUBRIC_V1.md",
    args.prompt,
    "skills-lock.json",
    "opencode.jsonc",
]

input_hashes = {}

for relative in tracked_inputs:
    path = ROOT / relative
    input_hashes[relative] = sha256_file(path) if path.exists() else None

git_head = command_output(["git", "rev-parse", "HEAD"])
opencode_version = command_output(["opencode", "--version"])

prompt = prompt_path.read_text()

cmd = [
    "opencode",
    "run",
    "--dir",
    str(ROOT),
    "--model",
    args.model,
    "--title",
    args.title,
    prompt,
]

started_at = datetime.now(timezone.utc)
start = time.perf_counter()
first_output_seconds = None

print(f"Benchmark: {args.benchmark}")
print(f"Model:     {args.model}")
print(f"Git HEAD:  {git_head}")
print(f"Run dir:   {run_dir.relative_to(ROOT)}")
print()
print("=== MODEL OUTPUT ===")

with response_path.open("w") as output:
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None

    for line in process.stdout:
        now = time.perf_counter()

        if first_output_seconds is None:
            first_output_seconds = now - start

        print(line, end="", flush=True)
        output.write(line)
        output.flush()

    return_code = process.wait()

elapsed = time.perf_counter() - start
finished_at = datetime.now(timezone.utc)

after_status = command_output(["git", "status", "--porcelain"])

elapsed_path.write_text(f"{elapsed:.3f}\n")
exit_path.write_text(f"{return_code}\n")

if first_output_seconds is None:
    first_output_path.write_text("UNKNOWN\n")
else:
    first_output_path.write_text(f"{first_output_seconds:.3f}\n")

manifest = {
    "benchmark": args.benchmark,
    "harness": "opencode",
    "model": args.model,
    "model_slug": slug,
    "prompt_file": args.prompt,
    "git_head": git_head,
    "git_clean_before": True,
    "repository_modified_by_run": bool(after_status),
    "repository_status_after": after_status or None,
    "opencode_version": opencode_version,
    "started_at_utc": started_at.isoformat(),
    "finished_at_utc": finished_at.isoformat(),
    "elapsed_seconds": round(elapsed, 3),
    "first_output_seconds": (
        round(first_output_seconds, 3)
        if first_output_seconds is not None
        else None
    ),
    "exit_code": return_code,
    "input_sha256": input_hashes,
}

manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

print()
print("=== BENCHMARK RESULT ===")
print(f"Elapsed seconds:      {elapsed:.3f}")
print(
    "First output seconds: "
    + (
        f"{first_output_seconds:.3f}"
        if first_output_seconds is not None
        else "UNKNOWN"
    )
)
print(f"Exit code:            {return_code}")
print(
    "Repository modified: "
    + ("YES" if after_status else "NO")
)
print(f"Evidence directory:   {run_dir.relative_to(ROOT)}")

sys.exit(return_code)
