"""SWE-bench Dataset Loader & Inspector.

Connects directly to Hugging Face datasets-server API to fetch, inspect,
and benchmark real-world software engineering issues from SWE-bench Lite / Verified.
Zero-dependency, pure Python urllib.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.parse


SWE_BENCH_API_URL = "https://datasets-server.huggingface.co/rows"


def fetch_swe_bench_instances(
    dataset: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    limit: int = 10,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Fetch instances directly from Hugging Face Datasets API."""
    params = urllib.parse.urlencode({
        "dataset": dataset,
        "config": "default",
        "split": split,
        "offset": offset,
        "limit": limit
    })
    url = f"{SWE_BENCH_API_URL}?{params}"
    headers = {"User-Agent": "Mozilla/5.0 (Reticle-Harness-SWEBench)"}

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)

    rows = data.get("rows", [])
    return [r.get("row", {}) for r in rows]


def get_instance_summary(instance: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a concise view of a SWE-bench instance."""
    return {
        "instance_id": instance.get("instance_id"),
        "repo": instance.get("repo"),
        "base_commit": instance.get("base_commit"),
        "problem_title": instance.get("problem_statement", "").splitlines()[0] if instance.get("problem_statement") else "",
        "fail_to_pass_tests": instance.get("FAIL_TO_PASS", []),
        "pass_to_pass_tests": instance.get("PASS_TO_PASS", []),
        "test_patch_size": len(instance.get("test_patch", "")),
        "gold_patch_size": len(instance.get("patch", ""))
    }


def cache_instances(instances: List[Dict[str, Any]], out_file: str | Path = "swe_bench_samples.json"):
    path = Path(out_file)
    path.write_text(json.dumps(instances, indent=2), encoding="utf-8")
    print(f"Cached {len(instances)} instances to {path}")


if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Fetching {count} sample instances from SWE-bench Lite...")
    instances = fetch_swe_bench_instances(limit=count)
    for inst in instances:
        summ = get_instance_summary(inst)
        print(f"\n--- [{summ['instance_id']}] ({summ['repo']}) ---")
        print(f"Title: {summ['problem_title']}")
        print(f"Base commit: {summ['base_commit']}")
        print(f"Failing tests to fix: {summ['fail_to_pass_tests']}")
