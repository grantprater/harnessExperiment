"""Cross-check a mutation bank on Linux: each task's mutated tree runs in the pinned OCI task image.

The banks are generated on the Windows host, while the cloud backend (and the OCI backend) run Linux. For every task
this rebuilds the mutated tree (git archive of base_commit + git apply of mutation_patch, tests kept), runs the task's
evaluator_test_files once in the image (podman run --cpus 1 --network none, read-only mount, PYTHONPATH as the
evaluator sets it), and records whether the failing set, minus the repo entry's excluded_tests, equals fail_to_pass
and whether every pass_to_pass test passes. Strictly sequential; one container at a time. No model calls.

Usage (from the repo root; the interpreter only needs the standard library):
  python experiments/mutation_tasks/check_linux.py --repo boltons --work-dir <scratch> [--out FILE] [--limit N]
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import generate
from evaluate_task import load_outcomes  # generate.py puts experiments/p6_pilot on sys.path

IMAGE = "localhost/reticle-p6-task:py313-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="repos.json entry")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--engine", default="podman")
    parser.add_argument("--limit", type=int, default=None, help="check only the first N tasks")
    parser.add_argument("--out", default=None, help="result JSON (default: linux_check.<repo>.json next to this script)")
    args = parser.parse_args()
    config = generate.load_repo_config(args.repo)
    excluded = set(config["excluded_tests"])
    tasks = json.loads((generate.HERE / config["tasks_file"]).read_text(encoding="utf-8"))["tasks"][:args.limit]
    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="mutation-linux-"))
    work.mkdir(parents=True, exist_ok=True)
    pristine = work / "pristine"
    shutil.rmtree(pristine, ignore_errors=True)
    generate.export(generate.ensure_repo(config), config["commit"], pristine)
    guest_path = "/w" if config["pythonpath"] == "." else "/w/src"
    env = dict(os.environ, MSYS_NO_PATHCONV="1")  # Git Bash: keep /w and /out as container paths
    results = []
    for task in tasks:
        workspace, xml = work / "ws", work / "linux.xml"
        generate.materialize(pristine, workspace, task["mutation_patch"])
        if xml.exists():
            xml.unlink()
        started = time.monotonic()
        subprocess.run([args.engine, "run", "--rm", "--cpus", "1", "--network", "none",
                        "-v", f"{workspace}:/w:ro", "-v", f"{work}:/out", "-e", "PYTHONDONTWRITEBYTECODE=1",
                        "-e", f"PYTHONPATH={guest_path}", "-w", "/w", args.image, "timeout", "300",
                        "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=/out/linux.xml",
                        *task["evaluator_test_files"]], capture_output=True, env=env)
        outcomes, errors = load_outcomes(xml)
        failing = sorted(t for t, s in outcomes.items() if s == "fail" and t not in excluded)
        p2p_bad = sorted(t for t in task["pass_to_pass"] if outcomes.get(t) != "pass")
        entry = {"task_id": task["task_id"], "failing_matches_fail_to_pass": failing == sorted(task["fail_to_pass"]),
                 "failing": len(failing), "fail_to_pass": len(task["fail_to_pass"]),
                 "extra_failing": sorted(set(failing) - set(task["fail_to_pass"])),
                 "fail_to_pass_not_failing": sorted(set(task["fail_to_pass"]) - set(failing)),
                 "pass_to_pass_not_passing": p2p_bad, "collection_errors": errors, "tests_seen": len(outcomes),
                 "seconds": round(time.monotonic() - started, 1)}
        entry["ok"] = entry["failing_matches_fail_to_pass"] and not p2p_bad and not errors
        results.append(entry)
        print(f"{task['task_id']} ok={entry['ok']} failing {len(failing)} (fail_to_pass {len(task['fail_to_pass'])}) "
              f"pass_to_pass not passing {len(p2p_bad)}; {entry['seconds']}s", flush=True)
    shutil.rmtree(work / "ws", ignore_errors=True)
    image_id = subprocess.run([args.engine, "image", "inspect", "--format", "{{.Id}}", args.image],
                              capture_output=True, text=True).stdout.strip()
    summary = {"repo": args.repo, "image": args.image, "image_id": image_id, "tasks": len(results),
               "ok": sum(r["ok"] for r in results), "not_ok": [r["task_id"] for r in results if not r["ok"]]}
    out = Path(args.out) if args.out else generate.HERE / f"linux_check.{args.repo}.json"
    out.write_text(json.dumps({"summary": summary, "tasks": results}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
