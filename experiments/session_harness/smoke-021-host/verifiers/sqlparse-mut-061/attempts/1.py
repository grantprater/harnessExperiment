"""
Regression test for sqlparse's `reindent` formatting of comma-separated
identifier lists (e.g. the columns in a SELECT statement).

Per docs/source/api.rst:

    ``wrap_after``
      The column limit (in characters) for wrapping comma-separated lists.
      If unspecified, it puts every item in the list on its own line.

``wrap_after`` defaults to 0 (i.e. "unspecified"). ReindentFilter's
`_process_identifierlist` however guards its line-wrapping logic with
`self.wrap_after > 0`, which means that with the default settings no
wrapping ever happens any more -- contradicting the documented behavior
and causing every SELECT column list to stay on a single line when
`reindent=True` is requested.
"""
import sqlparse


def test_identifier_list_wraps_each_item_on_its_own_line_by_default():
    # With reindent=True and no explicit wrap_after (i.e. wrap_after
    # "unspecified"/0), every item of a comma separated identifier list
    # must be put on its own line, per the documented default behavior.
    sql = 'select foo, bar, baz\nfrom table1\nwhere 1 = 2'
    formatted = sqlparse.format(sql, reindent=True)

    lines = [line.strip() for line in formatted.splitlines()]

    # Each identifier ends up on a line of its own (leading/trailing
    # whitespace used for alignment is intentionally not checked here).
    assert lines == [
        'select foo,',
        'bar,',
        'baz',
        'from table1',
        'where 1 = 2',
    ]
    # The buggy version keeps the whole identifier list on a single line.
    assert 'foo, bar, baz' not in formatted


def test_identifier_list_stays_on_one_line_when_it_fits_wrap_after():
    # When an explicit, sufficiently large wrap_after column limit is
    # given, a short identifier list that fits within that limit must
    # NOT be split across lines. This must keep working once the
    # default-wrapping bug above is fixed.
    sql = 'select foo, bar, baz\nfrom table1\nwhere 1 = 2'
    formatted = sqlparse.format(sql, reindent=True, wrap_after=100)

    assert formatted == 'select foo, bar, baz\nfrom table1\nwhere 1 = 2'
