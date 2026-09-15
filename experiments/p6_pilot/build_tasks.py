"""Build tasks.json from verification.json plus symptom-only task statements.

Statements describe observable behavior (from the upstream report and the fix's tests),
never the cause or the patch. Tests that require behavior a statement cannot state
without revealing the fix are excluded from acceptance, with the reason recorded.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

REPO_URLS = {
    "boltons": "https://github.com/mahmoud/boltons",
    "more-itertools": "https://github.com/more-itertools/more-itertools",
    "click": "https://github.com/pallets/click",
    "packaging": "https://github.com/pypa/packaging",
    "tomlkit": "https://github.com/python-poetry/tomlkit",
    "pyparsing": "https://github.com/pyparsing/pyparsing",
    "cachetools": "https://github.com/tkem/cachetools",
    "humanize": "https://github.com/python-humanize/humanize",
    "sqlparse": "https://github.com/andialbrecht/sqlparse",
    "marshmallow": "https://github.com/marshmallow-code/marshmallow",
    "markdown-it-py": "https://github.com/executablebooks/markdown-it-py",
}

STATEMENTS = {
    "boltons-474": (
        "`boltons.setutils.IndexedSet.update()` is documented to accept one or more iterables, but "
        "calling it with several fails: `IndexedSet([1]).update([2], [3])` raises `TypeError`, and "
        "passing tuples or iterators adds the argument objects themselves as members. Expected: "
        "`s = IndexedSet([1]); s.update([2, 1, 3], [], [3, 4, 2])` returns None and leaves "
        "`list(s) == [1, 2, 3, 4]` for list, tuple, and one-shot iterator arguments; tuple-valued "
        "elements stay elements (`IndexedSet().update([(1, 2)], [(3, 4), (1, 2)])` gives "
        "`[(1, 2), (3, 4)]`)."
    ),
    "boltons-475": (
        "`boltons.strutils.iter_splitlines()` corrupts ordinary text containing a space followed by 28 "
        "or 29: `list(iter_splitlines('February 28, 2026'))` returns `['February', ', 2026']`. "
        "`indent()` inherits the corruption. It should split on the Unicode line separator U+2028 and "
        "paragraph separator U+2029 (e.g. `'\\u2028first\\u2028second\\u2028'` -> `['', 'first', "
        "'second', '']`), leave text like 'February 28, or February 29 in a leap year' as one line, and "
        "`indent('February 28\\u2028February 29\\u2029March 1\\r\\nMarch 2', '  ')` should return "
        "`'  February 28\\n  February 29\\n  March 1\\n  March 2'`."
    ),
    "more-itertools-1270": (
        "`more_itertools.constrained_batches(['a', 'b', 'c'], 10, max_count=0)` yields all three items "
        "in one batch, and negative `max_count` values are silently ignored. A supplied `max_count` of "
        "zero or less should raise `ValueError` with a message containing 'maximum count must be "
        "greater than zero', raised before any input is consumed (also for empty input). "
        "`max_count=None` still means no limit, and `max_count=1` yields one-item batches."
    ),
    "more-itertools-1279": (
        "`more_itertools.one()` and `only()` ignore a custom `too_long` / `too_short` exception instance "
        "whose truth value is False (an exception class defining `__bool__` returning False) and raise "
        "the default `ValueError` instead. The supplied exception should always be raised. Also, when "
        "a custom `too_long` exception is supplied, the default error message (which calls `repr()` on "
        "the first items) must not be built, so items whose `__repr__` raises do not interfere."
    ),
    "packaging-1330": (
        "`packaging.metadata` treats the `charset` parameter of `Description-Content-Type` as "
        "case-sensitive. `Metadata.from_email()` with `Description-Content-Type: text/plain; "
        "charset=utf-8` (Metadata-Version 2.6) does not produce "
        "`meta.description_content_type == 'text/plain; charset=utf-8'`, and validation rejects "
        "`text/plain; charset=utf-8` and `text/plain; charset=Utf-8` even though they name UTF-8. Charset "
        "values that resolve to UTF-8 should be accepted case-insensitively; other charsets such as "
        "ascii remain invalid."
    ),
    "tomlkit-549": (
        "Assigning an array of tables over a dotted key swallows the following sibling on round-trip:\n"
        "```python\nimport tomlkit\ndoc = tomlkit.parse('a.b = 1\\nc.d = 2\\n')\naot = tomlkit.aot()\n"
        "t = tomlkit.table(); t['x'] = 9\naot.append(t)\ndoc['a'] = aot\nprint(tomlkit.dumps(doc))\n```\n"
        "prints `[[a]]\\nx = 9\\nc.d = 2\\n`, so `c.d` is captured by `[[a]]` and the top-level `c` is "
        "lost when reparsed. Expected output: `'c.d = 2\\n\\n[[a]]\\nx = 9\\n'`, which reparses to "
        "`{'c': {'d': 2}, 'a': [{'x': 9}]}`."
    ),
    "tomlkit-551": (
        "`tomlkit.string(value, multiline=True)` loses a leading newline on round-trip. For "
        "`s = tomlkit.string('\\nfoo', multiline=True)`, `str(s)` is `'\\nfoo'`, but parsing "
        "`f'k = {s.as_string()}\\n'` gives `'foo'`. A multiline string (basic or literal) whose value "
        "starts with `\\n` or `\\r\\n` must reparse to exactly the original value; values that do not "
        "start with a newline must render as before."
    ),
    "pyparsing-639": (
        "`pyparsing_common.as_datetime` produces the wrong microseconds for fractional seconds: "
        "`ppc.iso8601_datetime().add_parse_action(ppc.as_datetime).parse_string('1997-07-16T19:20:30.45')[0]` "
        "is `datetime(1997, 7, 16, 19, 20, 30, 449)` but should be `datetime(1997, 7, 16, 19, 20, 30, "
        "450000)`, matching `convert_to_datetime` and `datetime.fromisoformat`."
    ),
    "cachetools-408": (
        "Growing an existing entry in a size-bounded cache evicts an unrelated entry even when the result "
        "fits: with `c = cachetools.LRUCache(maxsize=10, getsizeof=lambda v: v)`, doing `c[3] = 3; "
        "c[4] = 4; c[4] = 7` leaves only key 4, although 3 + 7 == 10 fits. Expected: both keys remain "
        "and `currsize == 10`. Replacing with the same size or a smaller size must also keep both "
        "entries with the correct `currsize`. This applies to every cache class in the package."
    ),
    "humanize-329": (
        "`humanize.naturalsize()` shows a mantissa equal to the base instead of moving to the next unit "
        "when rounding crosses a unit boundary: `naturalsize(999999)` returns `'1000.0 kB'` (expected "
        "`'1.0 MB'`), `naturalsize(999999999)` -> expected `'1.0 GB'`, `naturalsize(999999999999)` -> "
        "`'1.0 TB'`, `naturalsize(1024**2 - 1, binary=True)` -> `'1.0 MiB'`, `naturalsize(1024**3 - 1, "
        "binary=True)` -> `'1.0 GiB'`, and `naturalsize(1024**2 - 1, gnu=True)` -> `'1.0M'`. Values at "
        "the largest suffix are unaffected."
    ),
    "sqlparse-865": (
        "`get_real_name()` returns the wrong component for names with more than two dotted parts: "
        "`sqlparse.parse('db.schema.tbl.col')[0].tokens[0].get_real_name()` returns `'schema'` but "
        "should return `'col'` (and `get_name()` should also return `'col'`), while `get_parent_name()` "
        "remains `'db'`. For `x.y.z AS w` the real name should be `'z'` with alias `'w'`; "
        "`mydb.sch.func(1)` should give `'func'`. Two-part names such as `a.b` -> `'b'` already work."
    ),
    "marshmallow-3016": (
        "`marshmallow.validate.URL()` rejects an absolute URL with a fragment right after the host: "
        "`validate.URL()('http://example.org#fragment')` raises `ValidationError: Not a valid URL.`, "
        "while `http://example.org/#fragment` passes. `http://example.org#fragment` and "
        "`http://user@example.com#fragment` should be valid, and a bare same-document reference `#frag` "
        "should be valid when relative URLs are allowed (`relative=True`, and `relative=True, "
        "absolute=False`)."
    ),
    "markdown-it-py-416": (
        "Rendering markdown that ends on a blockquote marker while a table is open inside the quote "
        "crashes with `IndexError: string index out of range`:\n```python\nfrom markdown_it import "
        "MarkdownIt\nMarkdownIt().enable('table').render('> | a | b |\\n> |---|---|\\n>')\n"
        "MarkdownIt('commonmark', {'html': False}).enable('table').render('> | a | b |\\n> |---|---|\\n>')\n"
        "```\nBoth calls should render without raising."
    ),
    "click-3805": (
        "`click._utils.Sentinel` members (such as `click._utils.UNSET`) do not survive `copy.copy`, "
        "`copy.deepcopy`, or `pickle` round-trips: the result is not the same singleton member (or the "
        "operation fails). Every duplication of a member should return the identical member object. As "
        "a consequence, `copy.copy`/`copy.deepcopy`/pickling of `click.Option(['--name'])`, whose "
        "`default` is `UNSET`, should give an option whose `default is UNSET` and `name == 'name'`."
    ),
}

EXCLUDED_ACCEPTANCE_TESTS = {
    "tomlkit-551": {
        "tests.test_api::test_create_string[kwargs13-\\nMy\\nString\\n-\"\"\"\\n\\nMy\\nString\\n\"\"\"]":
            "requires one specific rendering; stating it would reveal the fix and other renderings "
            "that round-trip correctly are equally valid",
    },
    "cachetools-408": {
        "tests.test_rr.RRCacheTest::test_getsizeof_replace_grow":
            "RRCache evicts a random entry, so the pre-fix outcome is nondeterministic: it failed in the "
            "first verification run and passed in the second",
    },
}


def main():
    verification = json.loads((HERE / "verification.json").read_text(encoding="utf-8"))
    tasks = []
    for task_id, statement in STATEMENTS.items():
        record = verification[task_id]
        if not record.get("verified"):
            raise SystemExit(f"{task_id} is not verified")
        excluded = EXCLUDED_ACCEPTANCE_TESTS.get(task_id, {})
        unknown = set(excluded) - set(record["fail_to_pass"]) - set(record["pass_to_pass"])
        if unknown:
            raise SystemExit(f"{task_id}: excluded tests not among verified tests: {sorted(unknown)}")
        tasks.append({
            "task_id": task_id,
            "repo": record["repo"],
            "repo_url": REPO_URLS[record["repo"]],
            "upstream_pr": f"{REPO_URLS[record['repo']]}/pull/{record['pr']}",
            "base_commit": record["base_commit"],
            "fix_commit": record["fix_commit"],
            "statement": statement,
            "evaluator_test_files": record["test_files"],
            "fail_to_pass": [t for t in record["fail_to_pass"] if t not in excluded],
            "excluded_fail_to_pass": excluded,
            "pass_to_pass": [t for t in record["pass_to_pass"] if t not in excluded],
            "skipped_after_fix": record["skipped_after_fix"],
            "gold_source_files": record["source_files"],
        })
    (HERE / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}, indent=2) + "\n",
                                     encoding="utf-8")
    print(f"wrote {len(tasks)} tasks")


if __name__ == "__main__":
    main()
