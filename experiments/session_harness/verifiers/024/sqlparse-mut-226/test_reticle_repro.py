"""
Regression test for sqlparse's grouping ``extend`` bug.

``sqlparse.sql.TokenList.group_tokens(..., extend=True)`` is used whenever
an already-built group (e.g. an ``IdentifierList``) needs to absorb more
trailing tokens -- for instance when a third, fourth, ... column is
appended to a comma separated column list (``group_identifier_list`` in
``sqlparse/engine/grouping.py`` calls ``group_tokens`` with
``extend=True`` for every comma after the first one).

sqlparse documents itself as a "non-validating SQL parser" whose parse
tree is a lossless re-arrangement of the input tokens: converting a
parsed ``Statement`` back to a string (``str(stmt)``) reproduces the
original SQL exactly, as shown in docs/source/intro.rst::

    >>> str(stmt)
    'select * from "someschema"."mytable" where id = 1'

No formatting options are involved in that guarantee -- plain
``sqlparse.parse()`` followed by ``str()`` must return the input
unchanged.

The regression is an off-by-one slice in the ``extend`` branch of
``TokenList.group_tokens``::

    subtokens = self.tokens[start_idx + 2:end_idx]   # buggy
    # should be:
    subtokens = self.tokens[start_idx + 1:end_idx]

``start_idx`` points at the already-existing group (e.g. the
``IdentifierList`` built from the first "a, b"). When a *second* comma
triggers another ``extend`` call, ``self.tokens[start_idx + 1]`` is
exactly the comma token that caused the merge, but the buggy slice skips
it. That token is still removed from the parent's token list (via
``del self.tokens[start_idx + 1:end_idx]``) but is never added to the
group, so it disappears from the tree entirely and from the serialized
output -- a three-(or more)-column list loses one of its commas purely
from parsing, with zero formatting options requested.
"""

import sqlparse


def test_parse_preserves_all_commas_in_three_column_list():
    sql = "select a, b, c from tbl"
    stmt = sqlparse.parse(sql)[0]
    # Parsing alone (no formatting options) must not alter the SQL at
    # all: every character of the input, including every comma between
    # the three selected columns, has to come back out unchanged.
    assert str(stmt) == sql


def test_parse_preserves_all_commas_in_four_column_list():
    sql = "select a, b, c, d from tbl"
    stmt = sqlparse.parse(sql)[0]
    # With a fourth column, group_identifier_list() performs the buggy
    # extend() merge twice; both of the interior commas must survive.
    assert str(stmt) == sql


def test_format_noop_preserves_all_commas_in_identifier_list():
    sql = "select a, b, c from tbl"
    # sqlparse.format() with no options enables grouping but attaches no
    # mutating filters, so it must behave as a no-op passthrough just
    # like the bare parse/str round trip above.
    assert sqlparse.format(sql) == sql
