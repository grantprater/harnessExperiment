import pytest
import sqlparse


def test_format_invalid_where_does_not_raise():
    """Regression test: formatting SQL with an incomplete/invalid WHERE
    clause must not crash sqlparse.

    This mirrors the long standing sqlparse regression test for an
    invalid WHERE clause (historically fixed under issue121/issue26):
    formatting malformed SQL should never raise an internal
    ValueError/IndexError -- sqlparse is explicitly designed to be
    tolerant of invalid input and simply return its best-effort
    formatting of the tokens it was given.
    """
    sql = 'INSERT INTO foo where'
    # Must not raise ValueError("None is not in list") or any other
    # internal exception.
    formatted = sqlparse.format(sql, reindent=True)

    # The trailing WHERE keyword must be preserved in the output -- an
    # invalid/incomplete clause should not cause sqlparse to silently
    # drop tokens from the input.
    assert formatted.strip().lower().endswith('where')


def test_format_invalid_where_preserves_tokens_without_reindent():
    """Even without reindent, formatting an invalid WHERE clause must
    not raise and must preserve all of the original SQL content.
    """
    sql = 'SELECT * FROM foo WHERE'
    formatted = sqlparse.format(sql)

    assert formatted.strip().lower() == sql.strip().lower()


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
