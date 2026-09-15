"""Fixed evaluator for one P6 task, run by AcceptanceRunner on a candidate snapshot copy.

Usage: evaluate_task.py <bundle_dir> <candidate_dir>

The bundle (outside the agent's workspace) holds task.json and, under files/, the fix
commit's whole top-level test trees plus its root pytest configuration. These replace the
candidate's copies, so test edits or added conftest hooks cannot change acceptance. Only a
JSON report is printed to stdout.

Per expected test ID the status is pass, fail, skip, or missing. A test whose module failed
to import counts as fail, and so does every test when the fixed conftest.py cannot import
(the candidate broke the package). Any other missing test is left out of coverage, so
AcceptanceRunner reports "unknown" rather than guessing. A pytest timeout is reported, not
scored.
"""

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUTPUT_TAIL_CHARS = 20_000
CONFTEST_ERROR = "<conftest import error>"


def load_outcomes(xml_path: Path):
    outcomes, collection_errors = {}, []
    if not xml_path.exists():
        return outcomes, collection_errors
    for case in ET.parse(xml_path).iter("testcase"):
        kinds = {child.tag for child in case}
        classname, name = case.get("classname") or "", case.get("name") or ""
        if not classname and "error" in kinds:
            # pytest reports a module that failed to import as an error case with an empty
            # classname and the module path as its name, e.g. name="tests.test_filesize"
            collection_errors.append(name)
        status = "fail" if kinds & {"failure", "error"} else "skip" if "skipped" in kinds else "pass"
        outcomes[f"{classname}::{name}"] = status
    return outcomes, collection_errors


def conftest_collection_errors(outcomes, output: str):
    """The conftest.py is a fixed input; if it cannot import, the candidate broke the package."""
    if not outcomes and "ImportError while loading conftest" in output:
        return [CONFTEST_ERROR]
    return []


def classify(expected, outcomes, collection_errors):
    statuses = {}
    for test_id in expected:
        module = test_id.split("::", 1)[0]
        if test_id in outcomes:
            statuses[test_id] = outcomes[test_id]
        elif CONFTEST_ERROR in collection_errors or any(
            error == module or module.startswith(error + ".") for error in collection_errors
        ):
            statuses[test_id] = "fail"
        else:
            statuses[test_id] = "missing"
    return statuses


def criterion(statuses, version):
    observed = sorted(t for t, s in statuses.items() if s in {"pass", "fail"})
    if any(s == "fail" for s in statuses.values()):
        outcome = "fail"
    elif statuses and all(s == "pass" for s in statuses.values()):
        outcome = "pass"
    else:
        outcome = "unknown"
    return {
        "outcome": outcome,
        "evaluator_version": version,
        "coverage_ids": observed,
        "failing": sorted(t for t, s in statuses.items() if s == "fail"),
        "missing": sorted(t for t, s in statuses.items() if s == "missing"),
        "skipped": sorted(t for t, s in statuses.items() if s == "skip"),
    }


def install_fixed_test_inputs(bundle: Path, candidate: Path, spec: dict) -> None:
    """Replace the candidate's test trees and root pytest configuration with the fixed copies.

    Whole directories are replaced, so files the candidate added (for example a conftest.py
    with reporting hooks) cannot influence acceptance. Managed root files absent from the fix
    commit are removed from the candidate.
    """
    files = bundle / "files"
    for root in spec["test_roots"]:
        shutil.rmtree(candidate / root, ignore_errors=True)
    for name in spec["managed_root_files"]:
        if not (files / name).exists() and (candidate / name).is_file():
            (candidate / name).unlink()
    for source in sorted(p for p in files.rglob("*") if p.is_file()):
        target = candidate / source.relative_to(files)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main() -> int:
    bundle, candidate = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    spec = json.loads((bundle / "task.json").read_text(encoding="utf-8"))
    install_fixed_test_inputs(bundle, candidate, spec)

    src = candidate / "src"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(src if src.is_dir() else candidate))
    for package in (src.iterdir() if src.is_dir() else []):  # setuptools-scm packages need _version.py
        init = package / "__init__.py"
        if init.exists() and "from ._version import" in init.read_text(encoding="utf-8") and not (package / "_version.py").exists():
            (package / "_version.py").write_text('__version__ = version = "0+local"\n', encoding="utf-8")

    xml_path = candidate.parent / "evaluation-junit.xml"
    timed_out, exit_code, output = False, None, ""
    try:
        completed = subprocess.run(
            [spec["python"], "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--junitxml={xml_path}", *spec["pytest_targets"]],
            cwd=candidate, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=spec["pytest_timeout_seconds"],
        )
        exit_code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    outcomes, collection_errors = load_outcomes(xml_path)
    collection_errors += conftest_collection_errors(outcomes, output)
    version = spec["evaluator_version"]
    report = {
        "criteria": {
            "fail-to-pass": criterion(classify(spec["fail_to_pass"], outcomes, collection_errors), version),
            "pass-to-pass": criterion(classify(spec["pass_to_pass"], outcomes, collection_errors), version),
        },
        "pytest_exit_code": exit_code,
        "pytest_timed_out": timed_out,
        "collection_errors": collection_errors,
        "observed_test_count": len(outcomes),
        "pytest_output_tail": output[-OUTPUT_TAIL_CHARS:],
    }
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
