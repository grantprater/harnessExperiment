"""
Reproduction test for the reported sqlparse regression.

Root cause: ``TokenList._token_matching`` builds the index range for a
reverse (``token_prev``) search as ``range(start - 2, -2, -1)``. Because the
stop value is ``-2`` (exclusive), the range includes the index ``-1``, which
Python interprets as "the last element of the list" rather than "one before
the first element". As a consequence, whenever ``token_prev`` is asked for
the token before index 0 (i.e. there truly is no previous token), it
incorrectly wraps around and returns the *last* token of the list instead of
``(None, None)`` as its own docstring promises.

This single off-by-one bug ripples through many higher level behaviours
that rely on "is there a token before this one?" checks, including:

* ``StripCommentsFilter``, which uses ``prev_ is None`` to decide whether a
  comment at the very start of a statement can be removed cleanly or needs a
  replacement whitespace token inserted (format: strip comments single/multi).
* ``ReindentFilter._split_statements``, which uses the same check ("only
  break if it's not the first token", see its own inline comment) to avoid
  inserting a spurious leading newline before the first DML/DDL keyword of a
  statement (format reindent: stmts, and the canonical example reproduced
  from docs/source/intro.rst).
"""

import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Token, TokenList


def test_token_prev_before_first_token_returns_none():
    """``TokenList.token_prev`` documents: "``None`` is returned if there's
    no previous token." Calling it on index 0 of a token list must therefore
    return ``(None, None)``, never the last token of the list.
    """
    tlist = TokenList([
        Token(T.Keyword.DML, 'SELECT'),
        Token(T.Whitespace, ' '),
        Token(T.Wildcard, '*'),
    ])

    idx, prev = tlist.token_prev(0, skip_ws=False)

    assert (idx, prev) == (None, None)


def test_format_strip_comments_leading_comment():
    """A comment at the very start of a statement has nothing before it, so
    stripping it must not leave behind a stray blank line. ``strip_comments``
    is documented as "comments are removed from the statements" -- removing a
    leading comment should yield exactly the remaining SQL, unchanged.
    """
    sql = '--comment\nselect * from foo'

    result = sqlparse.format(sql, strip_comments=True)

    assert result == 'select * from foo'


def test_format_reindent_matches_documented_example():
    """Reproduces the canonical ``reindent=True`` example shown in
    docs/source/intro.rst. Reindenting a statement must not insert a
    spurious leading blank line before the first keyword -- the formatted
    statement should start directly with the (upper-cased) first keyword.
    """
    sql = 'select * from foo where id in (select id from bar);'
    expected = (
        'SELECT *\n'
        'FROM foo\n'
        'WHERE id IN\n'
        '  (SELECT id\n'
        '   FROM bar);'
    )

    result = sqlparse.format(sql, reindent=True, keyword_case='upper')

    assert result == expected
