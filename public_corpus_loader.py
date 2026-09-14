"""Public Multi-Document Corpus Loader.

Provides zero-dependency loaders and cached access to real-world, publicly
available multi-document corpora:
1. HotpotQA (distractor split, via Hugging Face datasets-server):
   Multi-hop cross-document reasoning across 10 distinct articles per query.
2. Python Standards & Specifications (PEPs, via official python/peps repo):
   Deep multi-document technical specifications with cross-PEP syntax and scoping invariants.
3. FinanceBench (via Hugging Face datasets-server):
   SEC 10-K financial disclosures with multi-year disclosures and tables.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.parse


CACHE_DIR = Path(__file__).parent / "corpus_cache"
HF_API_URL = "https://datasets-server.huggingface.co/rows"
GITHUB_PEPS_BASE = "https://raw.githubusercontent.com/python/peps/main/peps"


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def fetch_hotpotqa_instances(
    split: str = "validation",
    limit: int = 10,
    offset: int = 0,
    use_cache: bool = True
) -> List[Dict[str, Any]]:
    """Fetch real multi-document QA instances from HotpotQA (distractor setting).
    
    Each instance contains:
    - id: Unique query identifier
    - question: The cross-document question
    - answer: Gold answer string
    - type: 'bridge' or 'comparison'
    - level: 'easy', 'medium', or 'hard'
    - supporting_facts: Gold supporting facts (title + sentence_id)
    - documents: List of dicts with {'title': str, 'text': str, 'sentences': list[str]}
    """
    cache_file = _ensure_cache_dir() / f"hotpotqa_{split}_{offset}_{limit}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    params = urllib.parse.urlencode({
        "dataset": "hotpotqa/hotpot_qa",
        "config": "distractor",
        "split": split,
        "offset": offset,
        "limit": limit
    })
    url = f"{HF_API_URL}?{params}"
    headers = {"User-Agent": "CognitiveHarness/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    results = []
    for r in data.get("rows", []):
        row = r.get("row", {})
        ctx = row.get("context", {})
        titles = ctx.get("title", [])
        sentences_list = ctx.get("sentences", [])
        
        docs = []
        for title, sents in zip(titles, sentences_list):
            docs.append({
                "title": title,
                "text": " ".join(sents),
                "sentences": sents
            })
            
        results.append({
            "id": row.get("id"),
            "question": row.get("question"),
            "answer": row.get("answer"),
            "type": row.get("type"),
            "level": row.get("level"),
            "supporting_facts": row.get("supporting_facts"),
            "documents": docs
        })

    if use_cache:
        cache_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def fetch_pep_document(pep_num: int, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch an official Python Enhancement Proposal specification from python/peps."""
    filename = f"pep-{pep_num:04d}.rst"
    cache_file = _ensure_cache_dir() / filename
    
    if use_cache and cache_file.exists():
        content = cache_file.read_text(encoding="utf-8")
    else:
        url = f"{GITHUB_PEPS_BASE}/{filename}"
        headers = {"User-Agent": "CognitiveHarness/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        if use_cache:
            cache_file.write_text(content, encoding="utf-8")

    lines = content.splitlines()
    title = f"PEP {pep_num}"
    for idx, line in enumerate(lines[:30]):
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break

    return {
        "pep_number": pep_num,
        "title": title,
        "filename": filename,
        "line_count": len(lines),
        "char_count": len(content),
        "content": content
    }


def fetch_pep_suite(pep_numbers: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Fetch a suite of interconnected PEPs (e.g., typing evolution: 484, 585, 695)."""
    if pep_numbers is None:
        pep_numbers = [484, 585, 695]
    return [fetch_pep_document(p) for p in pep_numbers]


def fetch_financebench_instances(
    limit: int = 10,
    offset: int = 0,
    use_cache: bool = True
) -> List[Dict[str, Any]]:
    """Fetch real SEC 10-K financial QA instances from FinanceBench."""
    cache_file = _ensure_cache_dir() / f"financebench_{offset}_{limit}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    params = urllib.parse.urlencode({
        "dataset": "PatronusAI/financebench",
        "config": "default",
        "split": "train",
        "offset": offset,
        "limit": limit
    })
    url = f"{HF_API_URL}?{params}"
    headers = {"User-Agent": "CognitiveHarness/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    results = []
    for r in data.get("rows", []):
        row = r.get("row", {})
        results.append({
            "id": row.get("financebench_id"),
            "company": row.get("company"),
            "doc_name": row.get("doc_name"),
            "question": row.get("question"),
            "answer": row.get("answer"),
            "justification": row.get("justification"),
            "evidence": row.get("evidence", [])
        })

    if use_cache:
        cache_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
