"""Regression tests for sqlparse's trailing-semicolon handling.

``sqlparse.engine.filter_stack.FilterStack.__init__`` decides whether to
register ``StripTrailingSemicolonFilter`` based on the ``strip_semicolon``
flag.  The public API (see ``sqlparse.split``'s docstring: "If True, remove
trailing semicolons (default: False)." and ``sqlparse.format``, which never
exposes/activates semicolon-stripping at all) documents that trailing
semicolons must be *kept* unless the caller explicitly asks to strip them.

The current implementation has the condition inverted
(``if not (strip_semicolon): ...append filter``), so by default (the common
case used by both ``sqlparse.format`` and ``sqlparse.split``) semicolons are
silently stripped, and explicitly asking to strip them (``strip_semicolon=
True``) leaves them untouched instead.  This single inversion is responsible
for a very large share of formatting/splitting regressions (any statement
ending in ';' is affected), matching the widely-reported regression
(including CLI/stdout output and reindenting of multiple statements, both of
which rely on semicolons being preserved by default).
"""

import sqlparse


def test_format_notransform_of_quoted_crlf():
    # With no formatting options requested, sqlparse.format() must act as a
    # (mostly) identity transform: nothing -- including the trailing
    # semicolon or the raw CRLF embedded inside the quoted string literal
    # (see sqlparse.utils.split_unquoted_newlines, which explicitly ignores
    # newlines that are inside quotes) -- should be changed.
    sql = "SELECT 'a\r\nb' FROM foo;"
    assert sqlparse.format(sql) == sql


def test_format_reindent_stmts_preserves_semicolons():
    # Reindenting multiple statements must keep each statement's trailing
    # semicolon (reindent never asks for semicolon stripping) and separate
    # the statements with a blank line, per ReindentFilter.process().
    sql = "select foo; select bar;"
    formatted = sqlparse.format(sql, reindent=True)
    assert formatted == "select foo;\n\nselect bar;"


def test_split_default_keeps_trailing_semicolons():
    # sqlparse.split(sql) docstring: "strip_semicolon: If True, remove
    # trailing semicolons (default: False)." -- so by default semicolons
    # must remain part of each returned statement string.
    sql = "SELECT 1; SELECT 2;"
    assert sqlparse.split(sql) == ["SELECT 1;", "SELECT 2;"]


def test_split_strip_semicolon_true_removes_semicolons():
    # Conversely, explicitly requesting strip_semicolon=True must remove the
    # trailing semicolons.
    sql = "SELECT 1; SELECT 2;"
    assert sqlparse.split(sql, strip_semicolon=True) == ["SELECT 1", "SELECT 2"]
