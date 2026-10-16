import pytest
import sqlparse


def test_format_invalid_where_trailing_does_not_raise():
    """Regression test (historically issue121/issue26): formatting SQL
    with an incomplete/invalid WHERE clause must not crash sqlparse with
    an internal ValueError/IndexError. sqlparse is explicitly designed to
    be tolerant of invalid input and just return its best-effort
    formatting of the tokens it was given.
    """
    sql = 'SELECT * FROM foo WHERE'
    # Must not raise ValueError("None is not in list") or any other
    # internal exception while reindenting.
    formatted = sqlparse.format(sql, reindent=True)
    assert 'WHERE' in formatted.upper()


def test_format_invalid_nested_where_does_not_raise():
    """A WHERE clause that itself contains an incomplete/invalid nested
    WHERE clause (e.g. inside a subquery) must not crash sqlparse either.
    This exercises the same grouping/reindent code path (group_where /
    ReindentFilter._process_where) but with the invalid WHERE clause
    nested one level deeper, which is the kind of case the issue121 fix
    was meant to cover for *any* WHERE clause, not just top-level ones.
    """
    sql = 'SELECT * FROM foo WHERE bar IN (SELECT baz FROM qux WHERE)'
    formatted = sqlparse.format(sql, reindent=True)
    assert formatted.upper().count('WHERE') == 2


def test_format_valid_where_clause_still_works():
    """Control case: formatting a well-formed WHERE clause must keep
    working (and keep producing a WHERE clause on its own line when
    reindent=True), so the fix for the invalid-where regression must
    not break ordinary, correct behaviour.
    """
    sql = 'SELECT * FROM foo WHERE bar = 1'
    formatted = sqlparse.format(sql, reindent=True)

    lines = [line.strip() for line in formatted.splitlines()]
    assert any(line.startswith('WHERE') for line in lines)
    assert 'bar = 1' in formatted
