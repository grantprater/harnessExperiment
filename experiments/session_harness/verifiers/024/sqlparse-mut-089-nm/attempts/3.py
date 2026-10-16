"""
Regression test for the sqlparse lexer whitespace regex.

keywords.SQL_REGEX contains the rule::

    (r'\\s+?', tokens.Whitespace),

The trailing ``?`` makes the quantifier *lazy*.  Since the lexer uses
``re.match`` (which only anchors at the start, not the end, of the match),
a lazy ``+?`` is satisfied by the smallest possible repetition, i.e. a
single whitespace character.  As a consequence every run of two or more
plain whitespace characters (spaces/tabs that are not part of a newline)
is tokenized as a separate ``Whitespace`` token per character instead of
one token holding the whole run.

Downstream code throughout ``sqlparse.filters`` assumes that a contiguous
run of whitespace is represented by exactly one token.  For example
``StripWhitespaceFilter._stripws_identifierlist`` (see issue140, "Removes
newlines before commas") only ever deletes the single token found
immediately before a comma.  When that run has been fragmented into many
one-character tokens, only the last of them gets removed and the rest of
the run leaks into the formatted output -- which is the regression
described in the report ("format: strip comments preserves whitespace",
"format reindent: identifier list with functions", etc.).

The correct, documented behaviour (consistent with every other rule in
``SQL_REGEX``, which greedily matches as much as possible, and with the
assumptions baked into the filters) is that the whitespace rule is
greedy, i.e. equivalent to ``r'\\s+'`` without the ``?``.
"""
import sqlparse
from sqlparse import tokens as T


def test_lexer_combines_consecutive_whitespace_into_single_token():
    # Two consecutive plain spaces must be lexed as ONE Whitespace token
    # holding both characters, not as two separate one-character tokens.
    stmt = sqlparse.parse("SELECT  1")[0]
    ws_tokens = [tok for tok in stmt.tokens if tok.ttype is T.Whitespace]

    assert len(ws_tokens) == 1
    assert ws_tokens[0].value == '  '


def test_format_strip_whitespace_removes_whole_run_before_comma():
    # issue140 / StripWhitespaceFilter._stripws_identifierlist: *all*
    # whitespace immediately preceding a comma in an identifier list must
    # be removed, regardless of how many characters it consists of.
    sql = 'SELECT a    , b FROM tbl'
    result = sqlparse.format(sql, strip_whitespace=True)

    assert result == 'SELECT a, b FROM tbl'


def test_format_reindent_identifier_list_with_functions_no_space_before_comma():
    # Same guarantee as above, but for an identifier list containing
    # function calls, formatted with reindent=True (which also runs
    # StripWhitespaceFilter). No whitespace run should ever survive
    # directly in front of a comma.
    sql = 'SELECT foo(x)    , bar(y) FROM tbl'
    result = sqlparse.format(sql, reindent=True)

    assert ' ,' not in result
    assert '  ,' not in result
