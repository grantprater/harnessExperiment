import sqlparse


def test_format_identifiercase():
    """Unquoted identifiers must have their case changed by identifier_case.

    Per sqlparse's documented behaviour (and CHANGELOG entry "Ignore
    identifier in double-quotes when changing cases"), only *unquoted*
    identifiers are affected by the identifier_case option. The current
    IdentifierCaseFilter has its quote-check inverted, so "bar" (unquoted)
    is left untouched instead of being upper-cased.
    """
    sql = 'select * from bar; -- select FOO\n'
    res = sqlparse.format(sql, identifier_case='upper')
    assert res == 'select * from BAR; -- select FOO\n'


def test_format_identifiercase_quotes():
    """Double-quoted identifiers must retain their original case.

    SQL quoting preserves the exact case of an identifier, so
    identifier_case must not touch it. The buggy filter currently does
    the opposite: it upper-cases quoted identifiers and ignores unquoted
    ones.
    """
    sql = 'select * from "foo".bar'
    res = sqlparse.format(sql, identifier_case='upper')
    assert res == sql


def test_issue469_copy_as_psql_command():
    """Regression test (issue469): quoted identifiers in a COPY command.

    A COPY statement (as typically run via the psql client) that
    references a double-quoted table name must keep that name's case
    untouched when identifier_case is requested, exactly like any other
    quoted identifier. The inverted quote-check in IdentifierCaseFilter
    currently upper-cases it, breaking this previously-passing check.
    """
    sql = 'copy "ttbl" to stdout'
    res = sqlparse.format(sql, identifier_case='upper')
    assert res == sql
