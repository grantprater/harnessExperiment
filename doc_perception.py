"""Document Perception Engine for Unstructured / General Domains.

Provides multi-scale sensory transduction for complex textual corpora:
1. Macro Sensor (`extract_doc_map`):
   - Extracts Table of Contents, major section headings, word counts, and structural hierarchy.
2. Mesoscopic Sensor (`extract_section`):
   - Retrieves an exact named section, clause, or table by title or heading anchor.
3. Foveated Saccade (`extract_passage`):
   - Pulls bounded paragraph/line slices with exact line coordinates for citation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class SectionNode:
    title: str
    level: int
    start_line: int
    end_line: int
    word_count: int
    preview: str


def _create_section_node(
    title: str,
    level: int,
    start_line: int,
    end_line: int,
    lines: List[str]
) -> SectionNode:
    """Construct a SectionNode with computed word count and 120-char preview."""
    section_lines = lines[start_line - 1 : end_line]
    word_count = sum(len(l.split()) for l in section_lines)
    preview = " ".join(l.strip() for l in section_lines if l.strip())[:120]
    return SectionNode(
        title=title,
        level=level,
        start_line=start_line,
        end_line=end_line,
        word_count=word_count,
        preview=preview + "..." if len(preview) == 120 else preview
    )


def _detect_heading(
    line: str,
    next_line: str,
    md_pattern: re.Pattern,
    rst_chars: set
) -> Tuple[bool, str, int, bool]:
    """Detect Markdown or RST underline headings. Return (found, title, level, is_rst)."""
    # 1. Markdown heading
    md_match = md_pattern.match(line)
    if md_match:
        return True, md_match.group(2).strip(), len(md_match.group(1)), False

    # 2. RST Underline heading
    s_line = line.strip()
    s_next = next_line.strip()
    if (
        s_line and s_next
        and len(s_next) >= 3
        and len(s_next) >= len(s_line)
        and all(c == s_next[0] for c in s_next)
        and s_next[0] in rst_chars
        and not line.startswith("..")
    ):
        char = s_next[0]
        rst_hierarchy = ["=", "-", "~", "^", "\"", "'", "`"]
        level = (rst_hierarchy.index(char) + 1) if char in rst_hierarchy else 3
        return True, s_line, level, True

    return False, "", 1, False


def parse_document_structure(text: str) -> List[SectionNode]:
    """Parse Markdown, RST, and structured text headings into a hierarchical section index."""
    lines = text.splitlines()
    sections: List[SectionNode] = []
    md_heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
    rst_underline_chars = set("=-~^\"'`:#*")

    current_title = "Document Header / Preamble"
    current_level = 1
    start_line = 1
    skip_next = False

    for idx in range(1, len(lines) + 1):
        if skip_next:
            skip_next = False
            continue

        line = lines[idx - 1]
        next_line = lines[idx] if idx < len(lines) else ""
        heading_found, new_title, new_level, is_rst = _detect_heading(
            line, next_line, md_heading_pattern, rst_underline_chars
        )

        if heading_found:
            skip_next = is_rst
            prev_end = idx - 2 if skip_next else idx - 1
            if prev_end >= start_line:
                sections.append(_create_section_node(current_title, current_level, start_line, prev_end, lines))

            current_level = new_level
            current_title = new_title
            start_line = idx + 2 if skip_next else idx + 1

    # Finalize last section
    if start_line <= len(lines):
        sections.append(_create_section_node(current_title, current_level, start_line, len(lines), lines))

    return sections


def extract_doc_map(file_path: Union[str, Path]) -> str:
    """Macro Sensor: Generate a compact structural map of a document."""
    path = Path(file_path)
    if not path.exists():
        return f"Error: Document '{path}' does not exist."

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    total_words = sum(len(l.split()) for l in lines)
    sections = parse_document_structure(text)

    out = [
        f"=== Document Structural Map: {path.name} ===",
        f"Total Lines: {len(lines)} | Total Words: {total_words:,} | Sections: {len(sections)}",
        "\nTable of Contents & Section Outlines:"
    ]

    for s in sections:
        indent = "  " * (s.level - 1)
        out.append(f"{indent}- [{s.title}] (L{s.start_line}-L{s.end_line}, {s.word_count} words)")
        if s.preview and s.title != "Document Header / Preamble":
            out.append(f"{indent}    preview: \"{s.preview}\"")

    out.append("=== End Document Map ===")
    return "\n".join(out)


def extract_section(
    file_path: Union[str, Path],
    section_name: str
) -> str:
    """Mesoscopic Sensor: Retrieve the complete text of a named section."""
    path = Path(file_path)
    if not path.exists():
        return f"Error: Document '{path}' does not exist."

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = parse_document_structure(text)

    # Match target section (exact or case-insensitive substring)
    target = None
    for s in sections:
        if s.title.lower() == section_name.lower():
            target = s
            break
    if not target:
        matches = [s for s in sections if section_name.lower() in s.title.lower()]
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            candidates = ", ".join(f"'{m.title}'" for m in matches)
            return f"Ambiguous section name '{section_name}'. Matches: {candidates}"

    if not target:
        avail = ", ".join(f"'{s.title}'" for s in sections[:10])
        return f"Section '{section_name}' not found in {path.name}. Available: {avail}"

    sec_lines = lines[target.start_line - 1 : target.end_line]
    formatted = [f"--- Section View: {target.title} ({path.name} L{target.start_line}-L{target.end_line}) ---"]
    for idx, l in enumerate(sec_lines, target.start_line):
        formatted.append(f"{idx:4d} | {l}")
    formatted.append(f"--- End Section ({len(sec_lines)} lines) ---")
    return "\n".join(formatted)


def extract_passage(
    file_path: Union[str, Path],
    start_line: int,
    end_line: int
) -> str:
    """Foveated Saccade: Retrieve an exact bounded line slice with line numbers."""
    path = Path(file_path)
    if not path.exists():
        return f"Error: Document '{path}' does not exist."

    lines = path.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    s = max(1, start_line)
    e = min(total, end_line)

    formatted = [f"--- Passage Saccade: {path.name} (L{s}-L{e} of {total}) ---"]
    for idx in range(s, e + 1):
        formatted.append(f"{idx:4d} | {lines[idx - 1]}")
    formatted.append("--- End Passage ---")
    return "\n".join(formatted)


if __name__ == "__main__":
    import sys
    target_doc = sys.argv[1] if len(sys.argv) > 1 else "ARCHITECTURE.md"
    print(extract_doc_map(target_doc))
