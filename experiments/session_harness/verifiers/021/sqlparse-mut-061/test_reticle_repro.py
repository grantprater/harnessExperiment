"""Regression test: sqlparse.format(..., reindent=True) must put every
identifier of a plain (non-VALUES, non-function-call) comma-separated
column list on its own line when ``wrap_after`` is left unspecified, as
documented in docs/source/api.rst::

    ``wrap_after``
      The column limit (in characters) for wrapping comma-separated lists.
      If unspecified, it puts every item in the list on its own line.

A regression in ``sqlparse/filters/reindent.py`` guards the newline
insertion in ``_process_identifierlist``'s default branch with
``self.wrap_after > 0 and ...``. Since ``wrap_after`` defaults to 0, this
guard disables the "one item per line" behaviour entirely, so
comma-separated identifier lists collapse onto a single line instead of
being split and aligned under the first column.
"""

import sqlparse


def test_reindent_identifier_list_default_wraps_each_item():
    sql = 'select foo, bar, baz from table1'
    formatted = sqlparse.format(sql, reindent=True)
    expected = (
        'select foo,\n'
        '       bar,\n'
        '       baz\n'
        'from table1'
    )
    assert formatted == expected


def test_reindent_identifier_list_with_where_wraps_each_item():
    # Mirrors the exact scenario from the bug report: an identifier list
    # followed by a WHERE clause. On the buggy code the columns stay on a
    # single line ('select foo, bar, baz\nfrom table1\nwhere 1 = 2'),
    # instead of being split one-per-line.
    sql = 'select foo, bar, baz from table1 where 1 = 2'
    formatted = sqlparse.format(sql, reindent=True)
    expected = (
        'select foo,\n'
        '       bar,\n'
        '       baz\n'
        'from table1\n'
        'where 1 = 2'
    )
    assert formatted == expected
