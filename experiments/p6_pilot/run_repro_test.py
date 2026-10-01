"""Run a task's frozen reproduction test on a candidate tree; print its counts as JSON (card 021's verifier).

Usage: python run_repro_test.py BUNDLE CANDIDATE [--with-output]

BUNDLE holds verifier.json ({"python", "timeout_seconds", "test_file"}), the test file and verifier-pytest.ini;
CANDIDATE is a scratch copy of the tree under test, never the model's workspace. The test is copied to the
candidate's root and run by the task interpreter with pytest, with the bundle's own empty ini (so the candidate's
pytest configuration is not read) and --noconftest (so a conftest.py the candidate added cannot rewrite outcomes).
Printed: collected, passed, failed (failures and errors), skipped, collection_error, exit_code, timed_out; and,
only with --with-output (verifier generation, never the agent's check tool), the last 3000 characters of pytest's
output.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

OUTPUT_TAIL_CHARS = 3000


def counts(xml_path: Path) -> dict:
    result = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "collection_error": False}
    if not xml_path.exists():
        return result
    for case in ET.parse(xml_path).iter("testcase"):
        kinds = {child.tag for child in case}
        if not (case.get("classname") or "") and "error" in kinds:
            result["collection_error"] = True  # a module that failed to import
            continue
        result["collected"] += 1
        if kinds & {"failure", "error"}:
            result["failed"] += 1
        elif "skipped" in kinds:
            result["skipped"] += 1
        else:
            result["passed"] += 1
    return result


def main(argv) -> int:
    bundle, candidate = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    with_output = "--with-output" in argv[3:]
    spec = json.loads((bundle / "verifier.json").read_text(encoding="utf-8"))
    test_name = spec["test_file"]
    shutil.copyfile(bundle / test_name, candidate / test_name)
    src = candidate / "src"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(src if src.is_dir() else candidate))
    xml_path = candidate.parent / "verifier-junit.xml"
    timed_out, exit_code, output = False, None, ""
    try:
        completed = subprocess.run(
            [spec["python"], "-m", "pytest", "-p", "no:cacheprovider", "-q", "--noconftest",
             "-c", str(bundle / "verifier-pytest.ini"), "--rootdir", str(candidate), f"--junitxml={xml_path}",
             test_name],
            cwd=candidate, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=spec["timeout_seconds"],
        )
        exit_code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    report = {**counts(xml_path), "exit_code": exit_code, "timed_out": timed_out}
    if with_output:
        report["output_tail"] = output[-OUTPUT_TAIL_CHARS:]
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
