import sqlparse


def test_format_reindent_keywords():
    """Basic keyword-based reindent must not introduce a spurious base
    indent level for the default (indent_after_first=False) case."""
    sql = 'select * from foo where bar = 1 order by id desc'
    result = sqlparse.format(sql, reindent=True)
    assert result == 'select *\nfrom foo\nwhere bar = 1\norder by id desc'


def test_format_reindent_keywords_between():
    """BETWEEN ... AND must stay on a single line, and the WHERE/FROM/
    ORDER BY lines must start at column 0 (no spurious indent)."""
    sql = 'select * from foo where id between 50 and 100 order by id'
    result = sqlparse.format(sql, reindent=True)
    assert result == (
        'select *\n'
        'from foo\n'
        'where id between 50 and 100\n'
        'order by id'
    )


def test_format_reindent_parenthesis():
    """A sub-select inside parenthesis must be indented by exactly one
    width level (2 spaces) relative to its own opening paren, not pushed
    an extra level deeper by a wrongly-initialized base indent."""
    sql = 'select count(*) from (select * from foo);'
    result = sqlparse.format(sql, reindent=True)
    assert result == (
        'select count(*)\n'
        'from\n'
        '  (select *\n'
        '   from foo);'
    )
