"""
Reproduction test for the sqlparse regression affecting ``strip_comments``.

The reported regression breaks (among others) the following previously
passing behaviours of ``sqlparse.format(..., strip_comments=True)``:

  * format: strip comments single
  * format: strip comments multi
  * format: strip comments preserves whitespace

These test functions reproduce exactly those three cases. The expected
values are the long-standing, documented behaviour of sqlparse's comment
stripping (see ``sqlparse/filters/others.py`` -- issue425/issue484 comments
describing that whitespace/line breaks around a removed comment must be
preserved so that the surrounding tokens are not accidentally concatenated,
and that comments are otherwise simply removed). They do not come from
whatever the currently-broken code happens to produce.
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


def test_strip_comments_preserves_whitespace():
    s = 'select"@x"-- foo\nfrom foo'
    s2 = 'select"@x"\nfrom foo'
    assert sqlparse.format(s, strip_comments=True) == s2
