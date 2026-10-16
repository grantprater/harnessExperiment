"""
Regression test for sqlparse's ``reindent_aligned`` formatting option.

``AlignedIndentFilter._split_kwds`` (sqlparse/filters/aligned_indent.py) is
supposed to use *only the first word* of a multi-word split keyword (such as
"LEFT JOIN" or "GROUP BY") when computing how many spaces to left-pad the
keyword with, so that it lines up with the other (generally shorter)
keywords like "FROM" and "JOIN" within the fixed-width keyword column. This
is exactly what the code's own comment says ("only consider the first word
as aligner") and it is also what the pre-existing GROUP/ORDER BY
compensation hack (the ``offset_ = 3`` "HACK" in ``_process_default``) is
tuned for.

The regression made ``_split_kwds`` use the *entire* matched keyword text
(``str(token)``) instead of just its first word for join keywords and
GROUP/ORDER BY. Because the fixed keyword column is only as wide as
``len('select')`` (6 characters), using the full multi-word text (e.g.
"LEFT JOIN" = 9 chars, "GROUP BY" = 8 chars) produces a negative pad amount,
which silently collapses to *zero* padding instead of lining up with the
other keywords -- breaking the alignment that ``reindent_aligned`` exists to
produce.
"""
import sqlparse


def test_reindent_aligned_joins():
    sql = 'SELECT a FROM foo JOIN bar LEFT JOIN baz'

    formatted = sqlparse.format(sql, reindent_aligned=True)

    # "FROM", "JOIN" and the first word of "LEFT JOIN" ("LEFT") are all
    # 4 characters long, so -- per the documented "only consider the first
    # word as aligner" behaviour -- they must all receive the same amount
    # of left padding (2 spaces) to right-align within the 6-character-wide
    # keyword column established by "SELECT".
    assert formatted == (
        'SELECT a\n'
        '  FROM foo\n'
        '  JOIN bar\n'
        '  LEFT JOIN baz'
    )


def test_reindent_aligned_group_by():
    sql = 'SELECT a, b FROM tbl GROUP BY a, b'

    formatted = sqlparse.format(sql, reindent_aligned=True)

    # "GROUP BY"'s alignment column is based on its first word ("GROUP",
    # 5 chars), giving it 1 space of left padding (6 - 5), which is exactly
    # what the pre-existing "HACK: make group/order by work" compensation
    # (offset_ = 3) in _process_default was written to match: the
    # continuation line for the second GROUP BY column ("b") lines up with
    # the first one directly after "GROUP BY ".
    assert formatted == (
        'SELECT a,\n'
        '       b\n'
        '  FROM tbl\n'
        ' GROUP BY a,\n'
        '          b'
    )
