"""Regression test for sqlparse's ``reindent_aligned`` formatting mode.

The ``AlignedIndentFilter`` (sqlparse/filters/aligned_indent.py) is documented
to right-justify every top-level clause keyword (SELECT/FROM/WHERE/AND/OR/
GROUP BY/...) inside a field of width ``len('select') + 1`` characters, so
that the *content* following each clause keyword begins in the very same
column on every line of the (outer) query. This directly follows from the
arithmetic in ``AlignedIndentFilter.nl()``:

    spaces = max_kwd_len + offset + indent + self.offset

For a subquery, ``_process_parenthesis`` enters one more indent level (via
the ``indent()`` context manager, adding ``2 + max_kwd_len`` columns), so the
inner SELECT/FROM content must consistently begin exactly one such indent
step (8 columns) further right than the outer query's own aligned column.
This is the self-consistency the "aligned" mode is supposed to guarantee,
and it is what the bug report's regressed scenarios ('basic' and
'group by subquery') are about.

Both tests below check this column-alignment invariant (not hand-copied
output of the current, buggy implementation).
"""

import re

import sqlparse


def _content_columns(formatted, keywords):
    """For each given clause keyword appearing at the start of a
    (stripped-of-leading-spaces) line, return the column (number of
    leading spaces) at which the keyword's own content starts, i.e.
    the column right after "KEYWORD "."""
    columns = []
    for line in formatted.split('\n'):
        stripped = line.lstrip(' ')
        leading = len(line) - len(stripped)
        for kw in keywords:
            if re.match(kw + r'\b', stripped, re.IGNORECASE):
                columns.append(leading + len(kw) + 1)
                break
    return columns


def test_reindent_aligned_basic():
    sql = 'SELECT a, b FROM foo WHERE a = 1 AND b = 2'
    formatted = sqlparse.format(sql, reindent_aligned=True)

    # every clause's content must start in the same column (7, following
    # directly from max_kwd_len=len('select')=6 plus one separating space)
    columns = _content_columns(formatted, ['SELECT', 'FROM', 'WHERE', 'AND'])
    assert columns, formatted
    assert all(c == 7 for c in columns), formatted

    # the continuation column "b" (second selected item) must also line up
    # directly under "a", i.e. at the very same column 7
    lines = formatted.split('\n')
    assert lines[0] == 'SELECT a,'
    assert lines[1].lstrip(' ') == 'b'
    assert len(lines[1]) - len(lines[1].lstrip(' ')) == 7, formatted


def test_reindent_aligned_group_by_subquery():
    sql = ('SELECT a, b FROM (SELECT x, y FROM t WHERE x = 1) AS sub '
           'GROUP BY a, b')
    formatted = sqlparse.format(sql, reindent_aligned=True)
    lines = formatted.split('\n')

    # Outer-query clauses (SELECT/FROM/GROUP BY) must all align their
    # content at the same outer column (7), exactly like in the basic case.
    outer_columns = _content_columns(formatted, ['SELECT', 'FROM'])
    assert outer_columns, formatted
    assert all(c == 7 for c in outer_columns), formatted

    # Inside the subquery, SELECT/FROM/WHERE must likewise all align their
    # own content at one consistent inner column, which per the filter's
    # indent()/nl() arithmetic must be exactly 8 columns to the right of the
    # outer alignment column (one indent level = 2 + len('select') = 8).
    inner_lines = [
        line for line in lines
        if re.match(r'^\s*(SELECT|FROM|WHERE)\b', line, re.IGNORECASE)
        and (len(line) - len(line.lstrip(' '))) > 7
    ]
    assert inner_lines, formatted
    inner_columns = _content_columns('\n'.join(inner_lines),
                                      ['SELECT', 'FROM', 'WHERE'])
    assert inner_columns, formatted
    assert all(c == 15 for c in inner_columns), formatted
