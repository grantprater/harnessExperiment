"""
Regression test for sqlparse.format(..., strip_whitespace=True).

The reported regression: `StripWhitespaceFilter._stripws_default` has its
ternary branches swapped, so a single, meaningful whitespace between two
tokens gets erased (turned into '') while sequences that *should* collapse
behave incorrectly. This makes otherwise-already-minimal SQL lose required
separating spaces, e.g. "select (select 2)" turns into "select(select2)",
and "select   1   from   foo" collapses spaces away entirely instead of
down to single spaces.
"""
import sqlparse


def test_strip_whitespace_keeps_single_separating_spaces():
    # Input already has the minimal whitespace sqlparse should produce;
    # strip_whitespace=True must therefore leave it unchanged.
    sql = 'select (select 2)'
    assert sqlparse.format(sql, strip_whitespace=True) == 'select (select 2)'


def test_strip_whitespace_collapses_runs_of_spaces_to_one():
    # Extra/duplicate whitespace must collapse down to a single space,
    # not disappear entirely.
    sql = 'select   1   from   foo'
    assert sqlparse.format(
        sql, strip_whitespace=True
    ) == 'select 1 from foo'


def test_strip_whitespace_removes_leading_and_trailing_whitespace():
    # Leading/trailing whitespace around the statement should be stripped,
    # while required internal separators remain intact.
    sql = '   select 1 from foo   '
    assert sqlparse.format(
        sql, strip_whitespace=True
    ) == 'select 1 from foo'
