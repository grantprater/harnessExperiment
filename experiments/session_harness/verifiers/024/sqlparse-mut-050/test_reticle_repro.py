"""
Regression test for sqlparse's strip_comments formatting option.

A recent change to sqlparse.sql.TokenList (performance/DoS hardening) made
TokenList.flatten() treat nested groups as opaque leaves instead of
recursing into them, and TokenList.__init__ now caches `.value` once at
construction time instead of recomputing it. Filters such as
StripCommentsFilter mutate a group's ``.tokens`` list in place (e.g. to
remove a Comment token) without updating that group's cached ``.value``.
Because of the flatten() change, serializing the statement to a string no
longer descends into such a mutated group to recompute its text from its
(correct, updated) children -- it instead reuses the stale cached
``.value``, so removed comment text leaks back into the formatted output.

This is triggered whenever a comment ends up grouped together with the
token that precedes it (see sqlparse.engine.grouping.align_comments),
which happens for a comment immediately following an identifier, as in
``... foo -- comment\\n...``.

Per docs/source/api.rst: "``strip_comments`` If ``True`` comments are
removed from the statements." and per the CHANGELOG ("Preserve line breaks
when removing comments (issue484)"), stripping a comment must remove the
comment text entirely while keeping the line break that terminated it (and
any later whitespace/indentation untouched).
"""

import sqlparse


def test_strip_comments_single():
    sql = 'select * from foo -- some comment goes here\nwhere x = 1'
    expected = 'select * from foo\nwhere x = 1'
    assert sqlparse.format(sql, strip_comments=True) == expected


def test_strip_comments_multi():
    sql = 'select * from foo /* some comment */\nwhere x = 1'
    expected = 'select * from foo\nwhere x = 1'
    assert sqlparse.format(sql, strip_comments=True) == expected


def test_strip_comments_preserves_whitespace():
    # Indentation on the line *after* the stripped comment must survive
    # untouched (issue484: line breaks -- and surrounding whitespace on
    # following lines -- are preserved when comments are removed).
    sql = 'select *\nfrom foo -- comment\n    where x = 1'
    expected = 'select *\nfrom foo\n    where x = 1'
    assert sqlparse.format(sql, strip_comments=True) == expected
