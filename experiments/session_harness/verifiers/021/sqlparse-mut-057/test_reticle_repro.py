import sqlparse
from sqlparse import sql


def _find_function(tlist):
    """Recursively search a token list for a grouped sql.Function."""
    for token in tlist.tokens:
        if isinstance(token, sql.Function):
            return token
        if token.is_group:
            found = _find_function(token)
            if found is not None:
                return found
    return None


def test_grouping_function_in_create_table_as_select_lowercase():
    # In `group_functions` (sqlparse/engine/grouping.py) the presence of an
    # "AS" keyword is checked with `tmp_token.value == 'AS'`, an exact,
    # case-sensitive comparison, while the CREATE/TABLE checks correctly use
    # `.upper()`. Because of this, a lower-case "as" in a
    # "CREATE TABLE ... AS SELECT ..." statement is not detected, the
    # function wrongly concludes there is no AS clause, and it bails out
    # before grouping any function calls in the SELECT part - even though
    # the exact same statement written in upper case is grouped correctly.
    upper = sqlparse.parse('CREATE TABLE foo AS SELECT bar(x) FROM baz')[0]
    lower = sqlparse.parse('create table foo as select bar(x) from baz')[0]

    assert _find_function(upper) is not None, (
        "sanity check: upper-case CREATE TABLE ... AS SELECT should group "
        "the function call"
    )
    assert _find_function(lower) is not None, (
        "lower-case CREATE TABLE ... AS SELECT should also group the "
        "function call, regardless of keyword casing"
    )


def test_grouping_function_in_create_table_as_select_mixed_case():
    # Same issue reproduced with mixed-case "As", which also fails the
    # literal 'AS' string comparison.
    stmt = sqlparse.parse('CREATE TABLE foo As SELECT bar(x) FROM baz')[0]
    assert _find_function(stmt) is not None


def test_create_table_without_as_still_skips_function_grouping():
    # Regression guard: plain CREATE TABLE definitions (no AS SELECT) must
    # keep their existing, correct behaviour of NOT treating the table
    # name followed by a column-definition parenthesis as a function call.
    stmt = sqlparse.parse('CREATE TABLE foo(id INT)')[0]
    assert _find_function(stmt) is None


def test_grouping_function_basic():
    # Baseline correct behaviour that must keep working: a simple function
    # call outside of any CREATE TABLE context is grouped as sql.Function.
    stmt = sqlparse.parse('foo(1, 2)')[0]
    assert isinstance(stmt.tokens[0], sql.Function)
