"""Regression test for sqlparse's `group_functions` grouping bug.

`sqlparse.engine.grouping.group_functions` deliberately skips grouping a
Name+Parenthesis pair into a `sql.Function` when the enclosing statement
looks like a plain ``CREATE TABLE ...`` (so the table name itself is not
mistaken for a function call), *unless* the statement also contains an
``AS`` keyword (as in ``CREATE TABLE t AS SELECT ...``), in which case
function calls appearing in the trailing ``SELECT`` clause should still be
grouped normally.

The two other keyword checks in that function (``CREATE`` and ``TABLE``)
are matched case-insensitively via ``.upper()``, but the ``AS`` check is
compared against the raw token value without normalizing case. Since
SQL keywords are case-insensitive, a lower-case ``as`` (a perfectly valid,
commonly used spelling) is not recognized, so the early-return guard fires
incorrectly and function calls in the SELECT list of a lower-case
``create table ... as select ...`` statement are silently left ungrouped.
"""
import sqlparse
from sqlparse import sql


def _find_functions(tlist):
    """Recursively collect all sql.Function instances in a token tree."""
    found = []
    for token in tlist.tokens:
        if isinstance(token, sql.Function):
            found.append(token)
        if token.is_group:
            found.extend(_find_functions(token))
    return found


def test_grouping_function_create_table_as_lowercase():
    # CREATE TABLE ... AS SELECT ... (CTAS) must still group function
    # calls that appear in the SELECT list, regardless of whether the
    # AS keyword is written in upper or lower case (SQL keywords are
    # case-insensitive).
    stmt = sqlparse.parse('create table foo as select bar() from baz')[0]
    functions = _find_functions(stmt)
    names = [f.get_real_name() for f in functions]
    assert 'bar' in names


def test_grouping_function_create_table_as_uppercase_still_works():
    # Sanity/regression guard: the upper-case spelling of CTAS already
    # works today and must keep working after the fix.
    stmt = sqlparse.parse('CREATE TABLE foo AS SELECT bar() FROM baz')[0]
    functions = _find_functions(stmt)
    names = [f.get_real_name() for f in functions]
    assert 'bar' in names


def test_grouping_function_plain_create_table_not_grouped():
    # Without an AS clause, a plain CREATE TABLE statement's table name
    # must NOT be grouped as a function call. This correct behavior must
    # be preserved by any fix.
    stmt = sqlparse.parse('CREATE TABLE foo (id INT)')[0]
    functions = _find_functions(stmt)
    names = [f.get_real_name() for f in functions]
    assert 'foo' not in names
