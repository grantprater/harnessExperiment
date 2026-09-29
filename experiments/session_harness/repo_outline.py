"""Counterfactual repository outline (aider-style repo map) for the mutation bank, and a pre-declared lexical rank.

Observation audit 001 (`observation-audit-001.md`) asks whether a coarse-by-default observation ladder would help:
an outline of every class/function with its signature and file:line address, from which the model zooms in. This
script builds that outline for a task's workspace with Python's `ast` and asks one question of it: would the task
statement plus the outline point at the mutated function?

The outline (built per task from the workspace the model saw: base commit + mutation patch, `tests/` hidden):
- every `.py` file of the workspace outside the hidden paths, one block per file:
  `path:` then one line per class/function/method (nested functions included, indented by depth) as
  `<line> class Name(bases)` or `<line> def name(signature)`; signatures are `ast.unparse` of the arguments;
- a reference count per symbol: occurrences of its bare name as an `ast.Name` id or `ast.Attribute` attr across the
  workspace (aider ranks its map by references; this is the simple stand-in);
- sizes are reported in bytes and approximate tokens (bytes / 4).

The score, DECLARED BEFORE ANY RANK WAS COMPUTED (committed in this file first; do not tune it on the ranks):
- Query = the variable parts of the statement only: the behaviour names (text between "Affected behaviour: " and
  ". The first failing check reports:") and the first failure message (the backtick-quoted text). The fixed template
  words of the statement are not used. "and N more" and "(N cases)" are removed.
- Tokenizer (query and documents): split on non-alphanumerics, split camelCase and snake_case, lowercase, strip one
  trailing "s" from tokens longer than 3 characters, drop pure numbers, tokens shorter than 2 characters and the
  stop words in `STOP`.
- Document per outline symbol = qualified name + file path components (without `.py`) + argument names + docstring.
- BM25 with k1 = 1.2, b = 0.75, idf = ln(1 + (N - df + 0.5) / (df + 0.5)), query term frequency counted.
- Rank of the gold symbol = number of symbols scoring >= its score (ties count against it; pessimistic).
  The gold symbol is the task's `mutated_function`; the enclosing method/top-level function (first two parts of a
  class member's qualified name, first part otherwise) is ranked too, for nested targets.
- File rank = rank of the gold file when each file is scored by its best symbol (pessimistic ties).
- Declared thresholds: the outline "points to" the gold function when the gold symbol or its enclosing method ranks
  <= 10; "points to the file" when the file ranks <= 3. A reference-ranked map cut at 1,024 tokens (aider's default
  `--map-tokens`) "contains" the gold function when its line survives the cut.

Usage:
  python experiments/session_harness/repo_outline.py --workspace BASE_DIR [--tasks FILE] [--task-ids FILE]
      [--json OUT] [--print-outline TASK_ID]
BASE_DIR is an export of the sqlparse base commit (f66d12c), e.g. `git -C <sqlparse clone> archive f66d12c | tar -x`.
No network, no model calls; runs in a second on one core.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = ROOT / "experiments" / "mutation_tasks" / "tasks.mutations.json"
DEFAULT_IDS = ROOT / "experiments" / "session_harness" / "E3-calibration-007-tasks.json"

STOP = {
    "the", "and", "or", "is", "are", "not", "of", "to", "in", "on", "for", "with", "an", "as", "at", "by", "be",
    "it", "its", "this", "that", "from", "has", "no", "object", "assert", "type", "types",
}
K1, B = 1.2, 0.75
POINTS_TO_SYMBOL, POINTS_TO_FILE, MAP_TOKENS = 10, 3, 1024


# ----------------------------------------------------------------------------------------------- workspace

def apply_patch(text: str, patch: str) -> str:
    """Apply a unified diff (single file, any number of hunks) to `text`; context lines must match."""
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    position = 0
    hunks = re.split(r"(?m)^@@ ", patch)[1:]
    for hunk in hunks:
        header, _, body = hunk.partition("\n")
        old_start = int(re.match(r"-(\d+)", header).group(1))
        out.extend(lines[position:old_start - 1])
        position = old_start - 1
        for raw in body.splitlines():
            if raw.startswith("\\"):
                continue
            tag, content = (raw[:1], raw[1:]) if raw else (" ", "")
            if tag == " ":
                if lines[position].rstrip("\r\n") != content:
                    raise ValueError(f"context mismatch at line {position + 1}: {content!r}")
                out.append(lines[position])
                position += 1
            elif tag == "-":
                if lines[position].rstrip("\r\n") != content:
                    raise ValueError(f"removed line mismatch at line {position + 1}: {content!r}")
                position += 1
            elif tag == "+":
                out.append(content + "\n")
    out.extend(lines[position:])
    return "".join(out)


def workspace_files(base: Path, task: dict) -> Dict[str, str]:
    """Text files of the task workspace: base export minus hidden paths, mutation patch applied."""
    hidden = [h.rstrip("/") + "/" for h in task.get("hidden_paths") or []]
    files: Dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if any(relative.startswith(h) for h in hidden):
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            continue
        files[relative] = raw.decode("utf-8", errors="replace")
    target = task["mutation_file"]
    files[target] = apply_patch(files[target], task["mutation_patch"])
    return files


# ----------------------------------------------------------------------------------------------- outline

@dataclass
class Symbol:
    file: str
    qualname: str
    kind: str  # class | def
    line: int
    end_line: int
    depth: int
    signature: str
    args: List[str]
    docstring: str
    refs: int = 0

    @property
    def name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]

    def render(self) -> str:
        return f"{self.line:>5} {'  ' * self.depth}{self.kind} {self.name}{self.signature}"


@dataclass
class Outline:
    symbols: List[Symbol] = field(default_factory=list)

    def by_file(self) -> Dict[str, List[Symbol]]:
        grouped: Dict[str, List[Symbol]] = {}
        for symbol in self.symbols:
            grouped.setdefault(symbol.file, []).append(symbol)
        return grouped

    def render(self, symbols: Optional[Sequence[Symbol]] = None) -> str:
        keep = set(id(s) for s in symbols) if symbols is not None else None
        blocks = []
        for file, members in self.by_file().items():
            shown = [s for s in members if keep is None or id(s) in keep]
            if shown:
                blocks.append(f"{file}:\n" + "\n".join(s.render() for s in shown))
        return "\n".join(blocks) + "\n"


def _signature(node: ast.AST) -> Tuple[str, List[str]]:
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases]
        return (f"({', '.join(bases)})" if bases else ""), []
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return f"({ast.unparse(args)})", names


def build_outline(files: Dict[str, str]) -> Outline:
    outline = Outline()
    names: Counter = Counter()
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        def visit(node: ast.AST, prefix: str, depth: int) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qual = f"{prefix}.{child.name}" if prefix else child.name
                    signature, args = _signature(child)
                    outline.symbols.append(Symbol(
                        path, qual, "class" if isinstance(child, ast.ClassDef) else "def", child.lineno,
                        child.end_lineno or child.lineno, depth, signature, args, ast.get_docstring(child) or ""))
                    visit(child, qual, depth + 1)
                else:
                    visit(child, prefix, depth)

        visit(tree, "", 0)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names[node.id] += 1
            elif isinstance(node, ast.Attribute):
                names[node.attr] += 1
    for symbol in outline.symbols:
        symbol.refs = names[symbol.name]
    return outline


def find_symbol(outline: Outline, file: str, qualname: str) -> Optional[Symbol]:
    for symbol in outline.symbols:
        if symbol.file == file and symbol.qualname == qualname:
            return symbol
    return None


def enclosing_qualname(outline: Outline, file: str, qualname: str) -> str:
    """The method (Class.method) or top-level function containing a nested target."""
    parts = qualname.split(".")
    first = find_symbol(outline, file, parts[0])
    if first is not None and first.kind == "class" and len(parts) >= 2:
        return ".".join(parts[:2])
    return parts[0]


# ----------------------------------------------------------------------------------------------- scoring

def tokens(text: str) -> List[str]:
    out = []
    for word in re.split(r"[^A-Za-z0-9]+", text):
        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", word):
            token = part.lower()
            if len(token) > 3 and token.endswith("s"):
                token = token[:-1]
            if len(token) < 2 or token.isdigit() or token in STOP:
                continue
            out.append(token)
    return out


def statement_query(statement: str) -> str:
    behaviour = re.search(r"Affected behaviour: (.*?)\. The first failing check reports:", statement, re.S)
    message = re.search(r"The first failing check reports: `(.*)`", statement, re.S)
    parts = [behaviour.group(1) if behaviour else "", message.group(1) if message else ""]
    text = " ".join(parts)
    text = re.sub(r"\band \d+ more\b", " ", text)
    text = re.sub(r"\(\d+ cases?\)", " ", text)
    return text


def symbol_document(symbol: Symbol) -> List[str]:
    path = symbol.file[:-3] if symbol.file.endswith(".py") else symbol.file
    return tokens(" ".join([symbol.qualname.replace(".", " "), path.replace("/", " "), " ".join(symbol.args),
                            symbol.docstring]))


def bm25_scores(outline: Outline, query: List[str]) -> List[float]:
    documents = [symbol_document(s) for s in outline.symbols]
    n = len(documents)
    average = sum(len(d) for d in documents) / max(n, 1)
    df: Counter = Counter()
    for document in documents:
        df.update(set(document))
    q = Counter(query)
    scores = []
    for document in documents:
        tf = Counter(document)
        score = 0.0
        for term, qtf in q.items():
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += qtf * idf * tf[term] * (K1 + 1) / (tf[term] + K1 * (1 - B + B * len(document) / average))
        scores.append(score)
    return scores


def pessimistic_rank(scores: Sequence[float], index: int) -> int:
    return sum(1 for s in scores if s >= scores[index])


def reference_map(outline: Outline, budget_tokens: int = MAP_TOKENS) -> List[Symbol]:
    """Symbols kept by a reference-ranked map cut at `budget_tokens` (bytes / 4), rendered with file headers."""
    ranked = sorted(outline.symbols, key=lambda s: (-s.refs, s.file, s.line))
    kept: List[Symbol] = []
    for symbol in ranked:
        trial = kept + [symbol]
        if len(outline.render(trial).encode("utf-8")) / 4 > budget_tokens:
            break
        kept = trial
    return kept


# ----------------------------------------------------------------------------------------------- per task

def analyse_task(base: Path, task: dict) -> dict:
    files = workspace_files(base, task)
    outline = build_outline(files)
    rendered = outline.render()
    names_only = "".join(f"{f}:\n" + "\n".join(f"{s.line:>5} {'  ' * s.depth}{s.kind} {s.name}" for s in ss) + "\n"
                         for f, ss in outline.by_file().items())
    query_text = statement_query(task["statement"])
    query = tokens(query_text)
    scores = bm25_scores(outline, query)
    gold_file, gold_qual = task["mutation_file"], task["mutated_function"]
    gold = find_symbol(outline, gold_file, gold_qual)
    enclosing_q = enclosing_qualname(outline, gold_file, gold_qual)
    enclosing = find_symbol(outline, gold_file, enclosing_q)
    index = {id(s): i for i, s in enumerate(outline.symbols)}
    gold_rank = pessimistic_rank(scores, index[id(gold)]) if gold else None
    enclosing_rank = pessimistic_rank(scores, index[id(enclosing)]) if enclosing else None
    file_scores: Dict[str, float] = {}
    for symbol, score in zip(outline.symbols, scores):
        file_scores[symbol.file] = max(file_scores.get(symbol.file, 0.0), score)
    file_list = list(file_scores.values())
    file_rank = (sum(1 for s in file_list if s >= file_scores[gold_file]) if gold_file in file_scores else None)
    ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:5]
    kept = reference_map(outline)
    kept_ids = set(id(s) for s in kept)
    per_file_bytes = {f: len((f + ":\n" + "\n".join(s.render() for s in ss) + "\n").encode("utf-8"))
                      for f, ss in outline.by_file().items()}
    best = min(r for r in (gold_rank, enclosing_rank) if r is not None) if (gold_rank or enclosing_rank) else None
    return {
        "task_id": task["task_id"],
        "gold_file": gold_file,
        "gold_symbol": gold_qual,
        "enclosing_symbol": enclosing_q,
        "gold_symbol_lines": [gold.line, gold.end_line] if gold else None,
        "query_text": query_text.strip(),
        "query_tokens": query,
        "symbols": len(outline.symbols),
        "files": len(per_file_bytes),
        "outline_bytes": len(rendered.encode("utf-8")),
        "outline_names_only_bytes": len(names_only.encode("utf-8")),
        "gold_file_outline_bytes": per_file_bytes.get(gold_file),
        "gold_file_bytes": len(files[gold_file].encode("utf-8")),
        "source_bytes": sum(len(t.encode("utf-8")) for f, t in files.items() if f.endswith(".py")),
        "gold_rank": gold_rank,
        "enclosing_rank": enclosing_rank,
        "best_rank": best,
        "gold_score": scores[index[id(gold)]] if gold else None,
        "file_rank": file_rank,
        "points_to_symbol": best is not None and best <= POINTS_TO_SYMBOL,
        "points_to_file": file_rank is not None and file_rank <= POINTS_TO_FILE,
        "in_reference_map_1k": bool((gold and id(gold) in kept_ids) or (enclosing and id(enclosing) in kept_ids)),
        "reference_map_symbols": len(kept),
        "top5": [[outline.symbols[i].file, outline.symbols[i].qualname, round(scores[i], 3)] for i in ranked],
        "per_file_outline_bytes": per_file_bytes,
    }


def load_tasks(path: Path) -> Dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {t["task_id"]: t for t in (data["tasks"] if isinstance(data, dict) else data)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, required=True, help="export of the sqlparse base commit")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-ids", type=Path, default=DEFAULT_IDS)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--print-outline", metavar="TASK_ID")
    args = parser.parse_args(argv)
    tasks = load_tasks(args.tasks)
    if args.print_outline:
        print(build_outline(workspace_files(args.workspace, tasks[args.print_outline])).render(), end="")
        return 0
    ids = json.loads(args.task_ids.read_text(encoding="utf-8"))["task_ids"]
    rows = [analyse_task(args.workspace, tasks[i]) for i in ids]
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("| Task | Gold symbol | Symbol rank | Enclosing rank | File rank | Points to fn (<=10) | File (<=3) | "
          "In 1k-token ref map | Query |")
    print("|---|---|--:|--:|--:|:-:|:-:|:-:|---|")
    for r in rows:
        print(f"| {r['task_id'][-3:]} | `{r['gold_symbol']}` | {r['gold_rank']} | {r['enclosing_rank']} | "
              f"{r['file_rank']} | {'yes' if r['points_to_symbol'] else 'no'} | "
              f"{'yes' if r['points_to_file'] else 'no'} | {'yes' if r['in_reference_map_1k'] else 'no'} | "
              f"{' '.join(r['query_tokens'])[:80]} |")
    first = rows[0]
    print(f"\nOutline: {first['symbols']} symbols in {first['files']} files; {first['outline_bytes']} bytes "
          f"(~{first['outline_bytes'] // 4} tokens) with signatures, {first['outline_names_only_bytes']} bytes names only;"
          f" source .py {first['source_bytes']} bytes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
