"""
Reproduction test for the sqlparse regression affecting ``strip_comments``.

The reported regression breaks (among others) the following previously
passing behaviours of ``sqlparse.format(..., strip_comments=True)``:

  * format: strip comments single
  * format: strip comments multi
  * format: strip comments preserves whitespace

These test functions reproduce those cases plus the directly related,
explicitly documented edge cases referenced by the comments inside
``sqlparse/filters/others.py`` itself:

  * issue425 -- a comment must not be replaced in a way that merges two
    previously separate tokens into one (e.g. ``a/*c*/b`` must not turn
    into ``ab``); a single space must take the place of the removed
    comment when neither neighbour is whitespace/parenthesis.
  * issue484 -- line breaks that were part of (or right after) a removed
    comment must be preserved so that statements spanning several lines
    keep their original line structure once comments are gone.
  * issue801 -- when a statement consists *only* of comments, stripping
    comments must remove all of them (not just the first one).

The expected values below are the long-standing, documented behaviour of
sqlparse's comment stripping; they are not derived from whatever the
currently broken code happens to produce.
"""

import sqlparse


def test_strip_comments_single():
    s = 'select *-- statement starting with comment\nfrom foo'
    s2 = 'select *\nfrom foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select * -- statement starting with comment\nfrom foo'
    s2 = 'select *\nfrom foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select -- statement starting with comment\n* from foo'
    s2 = 'select\n* from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select * from foo-- statement ending with comment'
    s2 = 'select * from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select * from foo -- statement ending with comment'
    s2 = 'select * from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    # Multiple single-line comments spread across several lines of the
    # same statement must all be removed while keeping the line breaks.
    s = ('select * from foo --comment1\n'
         'where bar = 1 --comment2\n'
         'order by baz')
    s2 = ('select * from foo\n'
          'where bar = 1\n'
          'order by baz')
    assert sqlparse.format(s, strip_comments=True) == s2


def test_strip_comments_multi():
    s = 'select/*comment*/*from foo'
    s2 = 'select *from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select/* comment */*from foo'
    s2 = 'select *from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select */*comment*/from foo'
    s2 = 'select * from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select */* comment */from foo'
    s2 = 'select * from foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    s = 'select *, /*comment*/\nfoo from bar'
    s2 = 'select *,\nfoo from bar'
    assert sqlparse.format(s, strip_comments=True) == s2

    # issue425: a comment with no surrounding whitespace that sits
    # between two tokens which are *not* parentheses must be replaced by
    # a single space -- the two neighbouring tokens must never end up
    # concatenated into one.
    s = 'select a/*comment*/b from foo'
    s2 = 'select a b from foo'
    assert sqlparse.format(s, strip_comments=True) == s2


def test_strip_comments_preserves_whitespace():
    s = 'select"@x"-- foo\nfrom foo'
    s2 = 'select"@x"\nfrom foo'
    assert sqlparse.format(s, strip_comments=True) == s2

    # issue484: the (blank) line structure around a multi-line comment
    # must be preserved once the comment itself is stripped.
    s = 'select * /* comment */\n\nfrom foo'
    s2 = 'select *\n\nfrom foo'
    assert sqlparse.format(s, strip_comments=True) == s2


def test_strip_comments_only_comment():
    # issue801: if the whole statement is just a comment, stripping
    # comments must remove it entirely instead of leaving it behind.
    s = '-- just a comment\n'
    assert sqlparse.format(s, strip_comments=True) == ''
