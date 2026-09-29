import sqlparse


def test_reindent_stmts_single_blank_line():
    """sqlparse.format(..., reindent=True) must join semicolon-separated
    statements with a single newline, not extra blank lines.

    This is the documented/well-known behaviour of ``reindent``: each
    statement keeps its own (re-indented) body and statements are simply
    put on consecutive lines, exactly the same way ``sqlparse.split()``
    reports them as separate statements without inserting blank lines
    between them.
    """
    sql = 'select foo; select bar'

    formatted = sqlparse.format(sql, reindent=True)

    assert formatted == 'select foo;\nselect bar'


def test_reindent_stmts_three_statements():
    """The same single-newline-per-statement rule must hold for more than
    two statements, confirming the fix generalizes and isn't a special
    case for exactly two statements.
    """
    sql = 'select foo; select bar; select baz'

    formatted = sqlparse.format(sql, reindent=True)

    assert formatted == 'select foo;\nselect bar;\nselect baz'
