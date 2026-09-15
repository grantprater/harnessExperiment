"""S2b E0 boundary probes through the real run tool (no model or API calls).

The same probe runs as a candidate command via ToolSuite.dispatch("run") on each backend.
trusted-local is the positive control: it must detect the host access it has, or the probe
proves nothing. isolated-oci is the boundary under test. Expectations are fixed in this file
before running; every observation is appended to results.jsonl as it completes, and the raw
tool outputs to raw.jsonl.

Usage (from the repo root):
  python experiments/session_harness/run_s2b_controls.py --run-name s2b-e0-1
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.execution import IsolatedOCIBackend  # noqa: E402
from reticle.runtime import LocalRuntime  # noqa: E402
from reticle.tools import ToolSuite  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNNER_VERSION = 2  # 2: chmod check after the uid-65534 chmod denial; Podman guest uses keep-id
TASK_PYTHON = ROOT / ".runtime" / "bugs-venv" / "Scripts" / "python.exe"
DEFAULT_OCI_IMAGE = "localhost/reticle-p6-task:py313-v1"
SIBLING_NEEDLE = "S2B-HIDDEN-EVALUATOR-7f3a"
CREDENTIAL_NEEDLE = "S2B-CREDENTIAL-SENTINEL-91c2"  # harmless marker, not a real secret
SOURCE_FILES = [
    "experiments/session_harness/run_s2b_controls.py",
    "reticle/execution/backends.py",
    "reticle/runtime/workspace.py",
    "reticle/tools/primitives.py",
]

# Fixed before running. Keys are check names; values per backend.
EXPECTED = {
    "trusted-local": {
        "probe_ran": True,
        "sibling_evaluator_readable": True,
        "credential_file_readable": True,
        "credential_env_present": False,  # the clean environment already strips host variables
        "host_listener_reachable": True,
        "workspace_write_ok": True,
        "workspace_chmod_ok": True,
        "source_write_changes_revision": True,
        "pytest_succeeded": True,
        "cache_directories_created": True,
        "cache_files_leave_revision_unchanged": True,
    },
    "isolated-oci": {
        "probe_ran": True,
        "sibling_evaluator_readable": False,
        "credential_file_readable": False,
        "credential_env_present": False,
        "host_listener_reachable": False,
        "public_network_reachable": False,
        "dns_resolves": False,
        "workspace_write_ok": True,
        "workspace_chmod_ok": True,
        "source_write_changes_revision": True,
        "pytest_succeeded": True,
        "cache_directories_created": True,
        "cache_files_leave_revision_unchanged": True,
    },
}

PROBE = r'''
import json, os, socket
from pathlib import Path

config = json.loads(Path("probe-config.json").read_text(encoding="utf-8"))
here = Path.cwd()


def read_attempt(paths, needle):
    found, errors = [], {}
    for path in paths:
        try:
            if needle in Path(path).read_text(encoding="utf-8", errors="replace"):
                found.append(path)
        except Exception as exc:
            errors[path] = type(exc).__name__
    return {"readable": bool(found), "paths_read": found, "errors": errors}


def connect(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return {"connected": True}
    except Exception as exc:
        return {"connected": False, "error": type(exc).__name__}


report = {
    "cwd": str(here),
    "sibling_evaluator": read_attempt([
        config["sibling_host_path"],
        str(here.parent / "evaluator" / "hidden_test.py"),
        "/workspace/../evaluator/hidden_test.py",
    ], config["sibling_needle"]),
    "credential_file": read_attempt([
        config["credential_host_path"], str(here.parent / "credential-sentinel.txt"),
    ], config["credential_needle"]),
    "credential_env_present": any(config["credential_needle"] in value for value in os.environ.values()),
    "environment_names": sorted(os.environ),
    "network": {
        "host_listener_loopback": connect("127.0.0.1", config["listener_port"]),
        "host_listener_gateway": connect("host.containers.internal", config["listener_port"]),
    },
}
if config["try_public_network"]:
    report["network"]["public_ip_443"] = connect("1.1.1.1", 443)
    try:
        socket.getaddrinfo("example.com", 443)
        report["network"]["dns"] = {"resolved": True}
    except Exception as exc:
        report["network"]["dns"] = {"resolved": False, "error": type(exc).__name__}
try:
    (here / "probe-write.txt").write_text("written by probe", encoding="utf-8")
    report["workspace_write"] = {"ok": True}
except Exception as exc:
    report["workspace_write"] = {"ok": False, "error": type(exc).__name__}
try:
    os.chmod(here / "probe-write.txt", 0o644)
    report["workspace_chmod"] = {"ok": True}
except Exception as exc:
    report["workspace_chmod"] = {"ok": False, "error": type(exc).__name__}
report["uid"] = os.getuid() if hasattr(os, "getuid") else None
print("PROBE_REPORT " + json.dumps(report, sort_keys=True))
'''


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, value) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def run_tool(tools: ToolSuite, call_id: str, command: str) -> str:
    return tools.dispatch("run", {"command": command, "timeout_seconds": 300}, call_id).content


def probe_backend(name: str, backend, interpreter: str, root: Path, port: int, results: Path, raw: Path) -> None:
    run_root = root / name
    workspace = run_root / "workspace"
    (workspace / "pkg").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (workspace / "tests" / "test_pkg.py").write_text(
        "import pkg\n\n\ndef test_value():\n    assert pkg.VALUE == 1\n", encoding="utf-8")
    (run_root / "evaluator").mkdir()
    sibling = run_root / "evaluator" / "hidden_test.py"
    sibling.write_text(f"# {SIBLING_NEEDLE}\n", encoding="utf-8")
    credential = run_root / "credential-sentinel.txt"
    credential.write_text(f"TOKEN={CREDENTIAL_NEEDLE}\n", encoding="utf-8")
    (workspace / "probe.py").write_text(PROBE, encoding="utf-8")
    (workspace / "probe-config.json").write_text(json.dumps({
        "sibling_host_path": str(sibling), "sibling_needle": SIBLING_NEEDLE,
        "credential_host_path": str(credential), "credential_needle": CREDENTIAL_NEEDLE,
        "listener_port": port, "try_public_network": name == "isolated-oci",
    }), encoding="utf-8")

    runtime = LocalRuntime(run_root / "session", workspace)
    tools = ToolSuite(runtime, interpreter=interpreter, backend=backend,
                      environment={"PYTHONIOENCODING": "utf-8"})
    observed = {}

    before_probe = runtime.workspace.revision()
    probe_output = run_tool(tools, "probe", "python probe.py")
    append_jsonl(raw, {"backend": name, "call": "probe", "content": probe_output})
    match = re.search(r"^PROBE_REPORT (.+)$", probe_output, re.MULTILINE)
    report = json.loads(match.group(1)) if match else {}
    observed["probe_ran"] = bool(match)
    if match:
        observed["sibling_evaluator_readable"] = report["sibling_evaluator"]["readable"]
        observed["credential_file_readable"] = report["credential_file"]["readable"]
        observed["credential_env_present"] = report["credential_env_present"]
        network = report["network"]
        observed["host_listener_reachable"] = (
            network["host_listener_loopback"]["connected"] or network["host_listener_gateway"]["connected"]
        )
        if "public_ip_443" in network:
            observed["public_network_reachable"] = network["public_ip_443"]["connected"]
            observed["dns_resolves"] = network["dns"]["resolved"]
        observed["workspace_write_ok"] = report["workspace_write"]["ok"]
        observed["workspace_chmod_ok"] = report["workspace_chmod"]["ok"]
    observed["source_write_changes_revision"] = runtime.workspace.revision() != before_probe

    before_pytest = runtime.workspace.revision()
    pytest_output = run_tool(tools, "pytest", "pytest -q tests")
    append_jsonl(raw, {"backend": name, "call": "pytest", "content": pytest_output})
    observed["pytest_succeeded"] = "status: success" in pytest_output.splitlines()[1]
    cache_paths = sorted(
        str(path.relative_to(workspace)) for path in workspace.rglob("*")
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}
    )
    observed["cache_directories_created"] = bool(cache_paths)
    observed["cache_files_leave_revision_unchanged"] = runtime.workspace.revision() == before_pytest

    for check, expected in EXPECTED[name].items():
        value = observed.get(check)
        append_jsonl(results, {
            "time": utc_now(), "backend": name, "check": check, "expected": expected,
            "observed": value, "match": value == expected,
        })
    append_jsonl(results, {"time": utc_now(), "backend": name, "check": "_detail",
                           "cache_paths": cache_paths, "probe_report": report})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--oci-image", default=DEFAULT_OCI_IMAGE)
    args = parser.parse_args()

    run_dir = HERE / "s2b_runs" / args.run_name
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; use a new --run-name")
    engine = IsolatedOCIBackend(args.oci_image).engine
    inspected = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", args.oci_image],
                               capture_output=True, text=True)
    if inspected.returncode or not inspected.stdout.strip():
        raise SystemExit(f"OCI image {args.oci_image} is not available: {inspected.stderr.strip()}")
    image_id = inspected.stdout.strip()
    oci = IsolatedOCIBackend(image_id, engine=engine)
    available, detail = oci.availability()
    if not available:
        raise SystemExit(detail)

    run_dir.mkdir(parents=True)
    (run_dir / "card.json").write_text(json.dumps({
        "id": "E0-s2b-boundaries", "runner_version": RUNNER_VERSION, "created_at": utc_now(),
        "oci_image": args.oci_image, "oci_image_id": image_id, "engine": engine,
        "container_user_arguments": oci.user_arguments(),
        "trusted_local_python": str(TASK_PYTHON), "expected": EXPECTED,
        "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_FILES},
        "decision_rule": "boundary gate passes iff every isolated-oci check matches and every "
                         "trusted-local positive control matches",
    }, indent=2), encoding="utf-8")

    os.environ["RETICLE_S2B_CREDENTIAL"] = CREDENTIAL_NEEDLE  # host-process sentinel
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    results, raw = run_dir / "results.jsonl", run_dir / "raw.jsonl"
    try:
        probe_backend("trusted-local", None, str(TASK_PYTHON), run_dir, port, results, raw)
        probe_backend("isolated-oci", oci, "python", run_dir, port, results, raw)
    finally:
        listener.close()

    for row in (json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()):
        if row["check"] != "_detail":
            print(f"{row['backend']:14} {row['check']:40} expected={row['expected']!s:5} "
                  f"observed={row['observed']!s:5} match={row['match']}")


if __name__ == "__main__":
    main()
