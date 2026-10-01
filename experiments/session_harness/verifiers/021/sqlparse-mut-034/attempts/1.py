import sqlparse


def test_issue227_gettype_cte():
    """Statement.get_type() must find the DML keyword (SELECT) that
    follows a WITH ... AS (...) common table expression definition.

    This mirrors the previously passing 'issue227 gettype cte' check.
    """
    sql = "with foo as (select 1) select * from foo"
    stmt = sqlparse.parse(sql)[0]
    assert stmt.get_type() == 'SELECT'


def test_comment_between_cte_clauses_issue632():
    """A comment placed between two CTE clause definitions must not
    prevent Statement.get_type() from finding the trailing DML keyword.

    This mirrors the previously passing
    'comment between cte clauses issue632' check.
    """
    sql = """with
    foo as (select 1),
    -- a comment between CTE clauses
    bar as (select 2)
    select * from foo, bar"""
    stmt = sqlparse.parse(sql)[0]
    assert stmt.get_type() == 'SELECT'


def test_plain_select_gettype_unaffected():
    """Sanity check: get_type() on a plain (non-CTE) statement must
    keep working as documented, so the fix does not regress this case.
    """
    stmt = sqlparse.parse("select * from foo")[0]
    assert stmt.get_type() == 'SELECT'
