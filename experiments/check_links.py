"""Tiny relative-markdown-link checker (stdlib only).

Scans every ``*.md`` file in the repo (excluding ``.git``, ``.runtime``, ``.venv``,
``node_modules``, and ``archive/``) for Markdown links of the form ``[text](target)``
whose target is a relative local-file reference (i.e. not an absolute URL with a
scheme like ``http://``, ``https://``, ``mailto:``, and not a bare ``#fragment``
within the same file). For each such link, resolves the target relative to the
linking file's directory (stripping any ``#fragment``) and reports it as
unresolved if the resolved path does not exist on disk.

Usage (from the repo root):
    python experiments/check_links.py

Exit status is 0 always; this is a reporting tool, not a gate. Output lists each
unresolved link as ``<source file>: <link target>``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".runtime", ".venv", "node_modules", "archive"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts)


def iter_markdown_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        if not is_excluded(path):
            yield path


def is_local_relative(target: str) -> bool:
    target = target.strip()
    if not target:
        return False
    if target.startswith("#"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        # Has a URL scheme (http:, https:, mailto:, file:, etc).
        return False
    if target.startswith("//"):
        return False
    return True


def resolve_target(md_file: Path, target: str) -> Path:
    target = target.split("#", 1)[0].strip()
    return (md_file.parent / target).resolve()


def check_links(root: Path):
    unresolved = []
    for md_file in iter_markdown_files(root):
        try:
            text = md_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            print(f"WARN: could not read {md_file.relative_to(root)}: {exc}", file=sys.stderr)
            continue
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if not is_local_relative(target):
                continue
            resolved = resolve_target(md_file, target)
            if not resolved.exists():
                unresolved.append((md_file.relative_to(root), target))
    return unresolved


def main() -> int:
    unresolved = check_links(ROOT)
    if not unresolved:
        print("No unresolved local markdown links found.")
        return 0
    print(f"{len(unresolved)} unresolved local markdown link(s):")
    for source, target in unresolved:
        print(f"{source.as_posix()}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
