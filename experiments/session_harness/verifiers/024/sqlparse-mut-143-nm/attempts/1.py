"""Regression tests for sqlparse.

These reproduce two of the behaviours reported as broken by the regression:

1. The "DoS prevention" limits added to the grouping engine
   (``sqlparse.engine.grouping.MAX_GROUPING_TOKENS`` /
   ``MAX_GROUPING_DEPTH``, see CHANGELOG "Fix uncontrolled CPU
   consumption in TokenList grouping") must not reject ordinary,
   non-malicious SQL.  A flat tuple list such as the contents of an
   ``IN (...)`` clause with a few thousand values is a normal,
   "reasonable" thing to see in real-world generated SQL and must
   continue to parse successfully into a proper IdentifierList, not
   raise ``SQLParseError``.

2. ``sqlparse.format(..., reindent_aligned=True)`` must keep producing
   its documented column-aligned output (see
   ``sqlparse.filters.aligned_indent.AlignedIndentFilter``): every
   clause keyword (``select``/``from``/...) is padded so that the
   values following it start in the same column, and every
   identifier after the first in a column list is placed on its own
   line, aligned under the first one.
"""

import pytest

import sqlparse
from sqlparse.exceptions import SQLParseError


def test_dos_prevention_reasonable_tuple_list_works():
    """A normal-sized IN (...) tuple list must still parse, not raise.

    The DoS-prevention limits exist to stop pathological/adversarial
    input (see CHANGELOG, "Security Fixes" / MAX_GROUPING_TOKENS /
    MAX_GROUPING_DEPTH in sqlparse/engine/grouping.py). A flat list of
    a few thousand plain integers -- the kind of thing produced by an
    ORM for a bulk "WHERE id IN (...)" query -- is reasonable,
    legitimate SQL and must keep working exactly like it did before
    the DoS-prevention feature was added.
    """
    values = ", ".join(str(i) for i in range(5000))
    sql = f"SELECT * FROM foo WHERE id IN ({values})"

    try:
        statements = sqlparse.parse(sql)
    except SQLParseError as exc:
        pytest.fail(
            "a reasonable, non-malicious tuple list must not be "
            f"rejected by the DoS-prevention limits: {exc}"
        )

    assert len(statements) == 1
    stmt = statements[0]

    # The statement must still be fully/correctly grouped: the WHERE
    # clause's parenthesis must contain a single IdentifierList with
    # all 5000 numbers as its identifiers.
    where = next(t for t in stmt.tokens if type(t).__name__ == "Where")
    parenthesis = next(
        t for t in where.flatten() if False
    ) if False else None  # placeholder, replaced below for clarity

    from sqlparse import sql as sql_mod

    paren = None
    for tok in where.tokens:
        if isinstance(tok, sql_mod.Parenthesis):
            paren = tok
    assert paren is not None, "IN (...) tuple was not grouped into a Parenthesis"

    idlist = None
    for tok in paren.tokens:
        if isinstance(tok, sql_mod.IdentifierList):
            idlist = tok
    assert idlist is not None, "the tuple list was not grouped into an IdentifierList"
    assert len(list(idlist.get_identifiers())) == 5000


def test_format_reindent_aligned_basic():
    """reindent_aligned must column-align a simple SELECT's clauses.

    This is the documented behaviour of ``reindent_aligned`` (see
    ``docs/source/api.rst``: "the indentations of the statements are
    changed, and statements are aligned by keywords") implemented by
    ``AlignedIndentFilter``: every selected column after the first
    goes on its own line indented to line up under the first column,
    and clause keywords (``from`` here) are padded so that the value
    following them lines up in that very same column.
    """
    sql = "select a, b as bb, c from table"
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = (
        "select a,\n"
        "       b as bb,\n"
        "       c\n"
        "from   table"
    )
    assert formatted == expected
