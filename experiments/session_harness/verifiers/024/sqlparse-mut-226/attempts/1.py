"""
Regression test for the sqlparse comment-stripping / comment-grouping bug.

Background
----------
sqlparse groups a trailing comment together with the token that precedes it
(see ``engine.grouping.align_comments``) and later ``group_tokens(...,
extend=True)`` folds the "glue" token (the whitespace/newline that sits
between the preceding token and the comment) into the resulting group -
see ``sql.py``'s ``TokenList.group_tokens``.

``filters.others.StripCommentsFilter._get_insert_token`` explicitly relies on
that whitespace/newline being preserved: "Returns either a whitespace or the
line breaks from token. See issue484 why line breaks should be preserved."
i.e. when a single-line comment is removed, any line break that was part of
the whitespace preceding/trailing the comment must survive so that the SQL
on either side of the (removed) comment stays on separate, valid lines.

The reported regression drops that glue token entirely, so stripping a
comment that precedes the ``WHERE`` keyword glues the previous token
directly onto ``where`` with no separator at all (e.g. ``foowhere`` instead
of ``foo\\nwhere``).
"""

import sqlparse


def test_strip_comments_preserves_newline_before_where():
    # Taken from sqlparse's own documented behaviour: stripping a trailing
    # single-line comment must preserve the line break that followed it, so
    # the next clause (WHERE) stays on its own line and is not glued to the
    # previous token.
    sql = 'select * from foo -- comment\nwhere (1 = 2)'
    res = sqlparse.format(sql, strip_comments=True)
    assert res == 'select * from foo\nwhere (1 = 2)'


def test_strip_comments_single_basic():
    # A comment between two otherwise-unrelated clauses ("select *" and
    # "from foo") must be removed while keeping the following clause on its
    # own line, exactly as it was before the comment was stripped.
    sql = 'select * -- a single comment\nfrom foo'
    res = sqlparse.format(sql, strip_comments=True)
    assert res == 'select *\nfrom foo'


def test_strip_comments_trailing_comment_keeps_tokens_separated():
    # Even without an explicit WHERE keyword, removing a comment that sits
    # directly after an identifier must not concatenate the identifier with
    # whatever keyword/token follows: a single space must remain so the
    # resulting SQL is still syntactically distinct tokens.
    sql = 'select * from foo -- comment\nwhere bar = 1'
    res = sqlparse.format(sql, strip_comments=True)
    assert res == 'select * from foo\nwhere bar = 1'
