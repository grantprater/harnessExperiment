import sqlparse


def test_format_invalid_where_with_stray_comma_does_not_raise():
    """Regression test: formatting SQL whose WHERE clause is malformed
    (here, a stray comma right after WHERE - clearly invalid SQL, but
    sqlparse is documented/designed to be tolerant of invalid input and
    just do its best-effort formatting instead of crashing) must not
    raise an internal ValueError while reindenting.

    Root cause being tested: ReindentFilter._process_where() looks up the
    WHERE keyword as a *direct* child of the grouped sql.Where node via
    ``tlist.token_next_by(m=(T.Keyword, 'WHERE'))`` and immediately calls
    ``tlist.insert_before(tidx, ...)``. For this input, the WHERE keyword
    ends up nested one level deeper inside an IdentifierList (because the
    stray comma causes the grouping code to fold WHERE together with the
    comma and the following identifier into an IdentifierList). This
    means ``token_next_by`` returns ``tidx=None``, and
    ``insert_before(None, ...)`` internally calls
    ``list.index(None)``, raising ``ValueError: None is not in list`` -
    exactly the exception from the report. sqlparse must not crash on
    this input; it must keep all of the original tokens in its output.
    """
    sql = 'SELECT * FROM foo WHERE, bar'

    formatted = sqlparse.format(sql, reindent=True)

    # Must not raise, and must not silently drop any of the input tokens.
    assert 'WHERE' in formatted.upper()
    assert 'BAR' in formatted.upper()


def test_format_invalid_nested_where_does_not_raise():
    """Same bug as above, but with the malformed WHERE clause nested one
    level deeper inside a subquery's parenthesis. This exercises the
    identical grouping/reindent code path for *any* WHERE clause in the
    statement, not just a top-level one, and must not crash either.
    """
    sql = 'SELECT * FROM foo WHERE bar IN (SELECT baz FROM qux WHERE, quux)'

    formatted = sqlparse.format(sql, reindent=True)

    assert formatted.upper().count('WHERE') == 2
    assert 'QUUX' in formatted.upper()


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
