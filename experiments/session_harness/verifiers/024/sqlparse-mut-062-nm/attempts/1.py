"""Regression test for sqlparse's ``reindent_aligned`` formatting mode.

The ``AlignedIndentFilter`` (sqlparse/filters/aligned_indent.py) implements a
well defined, self-consistent algorithm: every clause keyword is right
justified inside a field whose width equals ``len('select')`` (6 characters)
plus a single separating space, so that the *content* following every
top-level clause keyword (SELECT/FROM/WHERE/AND/OR/GROUP BY/...) starts at
the very same column. This is exactly what "aligned" reindenting is supposed
to achieve, and it follows directly from the arithmetic encoded in
``AlignedIndentFilter.nl()``:

    spaces = max_kwd_len + offset + indent + self.offset

where ``offset`` is ``-len(keyword)`` for a keyword line. Working this out by
hand for a basic SELECT/FROM/WHERE/AND query, and for a SELECT/FROM/GROUP BY
query (where GROUP BY additionally needs the "+3" offset hack documented in
``_process_default`` to keep its own continuation lines aligned under it),
gives the expected strings used below. These are the two scenarios
("basic" and a GROUP BY variant) that the bug report says regressed; prior to
the regression ``sqlparse.format(..., reindent_aligned=True)`` produced
exactly this output, and the content columns of every clause line are
internally consistent (all land on column 7, except the GROUP BY block which
consistently lands on column 10, matching the keyword's own extra length).
"""

import sqlparse


def test_reindent_aligned_basic():
    sql = 'SELECT a, b FROM foo WHERE a = 1 AND b = 2'
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = '\n'.join([
        'SELECT a,',
        '       b',
        '  FROM foo',
        ' WHERE a = 1',
        '   AND b = 2',
    ])

    assert formatted == expected


def test_reindent_aligned_group_by():
    sql = 'SELECT a, b FROM foo GROUP BY a, b'
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = '\n'.join([
        'SELECT a,',
        '       b',
        '  FROM foo',
        ' GROUP BY a,',
        '          b',
    ])

    assert formatted == expected
