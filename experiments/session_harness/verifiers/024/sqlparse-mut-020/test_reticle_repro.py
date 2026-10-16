"""
Regression test for: 'as in parentheses indents'.

Formatting SQL that contains an ``AS`` immediately adjacent to a
parenthesized sub-query (e.g. a CTE definition ``name AS (SELECT ...)``
or a derived-table alias ``(SELECT ...) AS name``) currently crashes
the reindent filter with::

    AttributeError: 'NoneType' object has no attribute 'is_group'

This happens inside ``sqlparse.filters.reindent.ReindentFilter._process_parenthesis``,
which looks up the opening ``(`` token of the parenthesis group and then
computes an offset for it. When the lookup unexpectedly returns ``None``
(the bug), the subsequent call into ``_flatten_up_to_token`` dereferences
``None.is_group`` and blows up.

The intended/documented behaviour of ``sqlparse.format(..., reindent=True)``
is to never raise on syntactically valid SQL, to keep every token of the
original statement (formatting only rearranges/collapses whitespace), and
to put the body of a parenthesized sub-query on its own, more indented
line -- exactly as it already does for plain ``FROM (SELECT ...)``
constructs (see the ``is_dml_dll`` handling in ``_process_parenthesis``).
These expectations come from the formatter's own stated purpose (pretty
printing without altering semantics) and from the existing, working
indentation logic for sub-queries in parentheses -- not from whatever the
currently-broken code happens to output.
"""
import re

import pytest

import sqlparse


def _normalized_tokens(sql):
    """Return the significant (non-whitespace) tokens of *sql* as a list.

    Used to make sure reindenting never drops or duplicates SQL content.
    """
    return re.findall(r'\S+', sql)


@pytest.mark.parametrize('sql', [
    # CTE definition: "AS" directly followed by a parenthesized sub-query.
    'WITH cte AS (SELECT a FROM tbl) SELECT a FROM cte',
    # Derived table: a parenthesized sub-query directly followed by "AS".
    'SELECT * FROM (SELECT a FROM tbl) AS cte',
])
def test_as_in_parenthesis_does_not_crash_reindent(sql):
    # This is the core regression: formatting must not raise.
    formatted = sqlparse.format(sql, reindent=True)

    # Formatting must not drop or invent SQL content.
    assert _normalized_tokens(formatted) == _normalized_tokens(sql)


def test_as_in_parenthesis_indents_subquery_body():
    sql = 'WITH cte AS (SELECT a FROM tbl) SELECT a FROM cte'
    formatted = sqlparse.format(sql, reindent=True)

    lines = formatted.splitlines()
    # Find the line that opens the sub-query (contains the "(") and the
    # line holding the inner SELECT that follows it.
    open_line_idx = next(
        i for i, line in enumerate(lines) if '(' in line
    )
    assert open_line_idx + 1 < len(lines), (
        "expected the sub-query body to be printed on its own line:\n"
        f"{formatted!r}"
    )
    inner_line = lines[open_line_idx + 1]
    assert 'SELECT' in inner_line.upper()

    # The sub-query body must be indented further than the line that
    # opens the parenthesis, mirroring sqlparse's existing behaviour for
    # "FROM (SELECT ...)" style sub-queries.
    open_indent = len(lines[open_line_idx]) - len(lines[open_line_idx].lstrip(' '))
    inner_indent = len(inner_line) - len(inner_line.lstrip(' '))
    assert inner_indent > open_indent
