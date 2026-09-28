"""Verify candidate real-repo bugs: new tests fail before the fix and pass after it.

For each (repo, merge commit): pre-fix = first parent. Only the commit's test-file
changes are applied to the pre-fix tree; source changes are withheld. Outcomes are
parsed from pytest's JUnit XML so no pass/fail is inferred from text.
"""

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOS = ROOT / ".runtime" / "bug-mining" / "repos"  # clones of the repos in build_tasks.REPO_URLS
WORK = ROOT / ".runtime" / "bug-mining" / "work"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from interpreters import task_python  # noqa: E402

PY = str(task_python(ROOT))  # pytest, tzdata, freezegun, mdurl, ...

CANDIDATES = [
    ("boltons", "a180020c76", 474), ("boltons", "45a251181f", 475),
    ("more-itertools", "cd47ab22e8", 1270), ("more-itertools", "b2f3aff763", 1279),
    ("packaging", "abf000549c", 1330), ("tomlkit", "67d3e86502", 549),
    ("tomlkit", "8cd44f58b4", 551), ("pyparsing", "73a8b553fb", 639),
    ("cachetools", "39b31bc", 408), ("humanize", "823ad6096e", 329),
    ("sqlparse", "f66d12c245", 865), ("marshmallow", "902f99c415", 3016),
    ("markdown-it-py", "1b7ef65639", 416), ("click", "4295457", 3805),
]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def is_test(path):
    parts = path.lower().split("/")
    return parts[0] in {"tests", "test", "testing"} or parts[-1].startswith("test_") or parts[-1].endswith("_test.py")


def run_pytest(tree, test_files, tag):
    xml = WORK / f"{tag}.xml"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    src = tree / "src"
    env["PYTHONPATH"] = str(src if src.is_dir() else tree)
    for pkg in (src.iterdir() if src.is_dir() else []):  # setuptools-scm packages need a generated _version.py
        init = pkg / "__init__.py"
        if init.exists() and "from ._version import" in init.read_text(encoding="utf-8") and not (pkg / "_version.py").exists():
            (pkg / "_version.py").write_text('__version__ = version = "0+local"\n', encoding="utf-8")
    proc = subprocess.run([PY, "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--junitxml={xml}", *test_files],
                          cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=900)
    outcomes = {}
    if xml.exists():
        for case in ET.parse(xml).iter("testcase"):
            test_id = f"{case.get('classname')}::{case.get('name')}"
            kinds = {child.tag for child in case}
            outcomes[test_id] = ("fail" if kinds & {"failure", "error"} else "skip" if "skipped" in kinds else "pass")
    return outcomes, proc.returncode, proc.stdout[-1500:] + proc.stderr[-1500:]


def worktree(repo, commit, name):
    path = WORK / name
    if path.exists():
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], capture_output=True)
        shutil.rmtree(path, ignore_errors=True)
    git(repo, "worktree", "add", "--detach", str(path), commit)
    return path


def verify(repo_name, merge, pr):
    repo = REPOS / repo_name
    fix = git(repo, "rev-parse", merge).strip()
    base = git(repo, "rev-parse", f"{fix}^1").strip()
    changed = [l.split("\t") for l in git(repo, "diff", "--name-status", base, fix).splitlines()]
    tests = [p[-1] for p in changed if is_test(p[-1]) and p[-1].endswith(".py") and p[0] != "D"]
    # Tests defined in a package __init__ (mixins) are only collected via the test modules that use them.
    targets = sorted({str(Path(t).parent).replace("\\", "/") if t.endswith("__init__.py") else t for t in tests})
    sources = [p[-1] for p in changed if p[-1].endswith(".py") and not is_test(p[-1])]
    tag = f"{repo_name}-{pr}"
    pre = worktree(repo, base, tag + "-pre")
    for t in tests:  # apply only the fix's test files to the pre-fix tree
        (pre / t).parent.mkdir(parents=True, exist_ok=True)
        (pre / t).write_bytes(subprocess.run(["git", "-C", str(repo), "show", f"{fix}:{t}"], capture_output=True, check=True).stdout)
    before, rc_before, tail_before = run_pytest(pre, targets, tag +"-pre")
    post = worktree(repo, fix, tag + "-post")
    after, rc_after, tail_after = run_pytest(post, targets, tag +"-post")
    fail_to_pass = sorted(t for t in after if after[t] == "pass" and before.get(t) == "fail")
    pass_to_pass = sorted(t for t in after if after[t] == "pass" and before.get(t) == "pass")
    broken_after = sorted(t for t in after if after[t] == "fail")
    return {
        "repo": repo_name, "pr": pr, "fix_commit": fix, "base_commit": base,
        "source_files": sources, "test_files": tests,
        "fail_to_pass": fail_to_pass, "pass_to_pass_count": len(pass_to_pass), "pass_to_pass": pass_to_pass,
        "skipped_after_fix": sorted(t for t in after if after[t] == "skip"),
        "failing_after_fix": broken_after, "tests_before": len(before), "tests_after": len(after),
        "rc_before": rc_before, "rc_after": rc_after,
        "tail_before": tail_before if not before else "", "tail_after": tail_after if (not after or broken_after) else "",
        "verified": bool(fail_to_pass) and not broken_after,
    }


if __name__ == "__main__":
    WORK.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    results = []
    for repo_name, merge, pr in CANDIDATES:
        if only and f"{repo_name}-{pr}" not in only:
            continue
        try:
            r = verify(repo_name, merge, pr)
        except Exception as exc:  # record, never hide
            r = {"repo": repo_name, "pr": pr, "verified": False, "error": repr(exc)[:800]}
        results.append(r)
        print(json.dumps({k: r.get(k) for k in ("repo", "pr", "verified", "source_files", "fail_to_pass", "pass_to_pass_count", "failing_after_fix", "error")}), flush=True)
        if not r.get("verified"):
            print("   before:", (r.get("tail_before") or "")[-600:], "\n   after:", (r.get("tail_after") or "")[-600:], flush=True)
    out = WORK / "verification.json"
    existing = json.loads(out.read_text()) if out.exists() else {}
    existing.update({f"{r['repo']}-{r['pr']}": r for r in results})
    out.write_text(json.dumps(existing, indent=2))
