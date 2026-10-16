"""
Regression test for sqlparse's token/representation regression.

Bug summary: ``sqlparse.sql.Token._get_repr_name`` (used both by
``Token.__repr__`` and by ``TokenList._pprint_tree``) is supposed to report
the *most specific* component of a token's type, e.g. ``DML`` for a
``Token.Keyword.DML`` token, ``Integer`` for ``Token.Literal.Number.Integer``
and ``Single`` for ``Token.Literal.String.Single``. A regression changed the
implementation to pick the second-to-last dotted component instead of the
last one, so it now reports the *parent* type (``Keyword``, ``Number``,
``String``) instead of the specific subtype. This breaks ``repr()`` of
tokens and the output of ``TokenList._pprint_tree`` (used e.g. by
``sqlparse.cli`` and documented as a debugging helper).
"""
import io
import re

import sqlparse
from sqlparse import tokens as T


def _repr_cls(token):
    """Extract the class name sqlparse puts at the front of Token.__repr__."""
    match = re.match(r"^<(\S+)\s", repr(token))
    assert match is not None, "unexpected repr format: %r" % (repr(token),)
    return match.group(1)


def test_token_repr_uses_most_specific_type_name():
    # 'SELECT' is tokenized as Keyword.DML and '2' as Number.Integer.
    # repr() is documented/intended to show the most specific (leaf)
    # component of the token type, not an ancestor type.
    stmt = sqlparse.parse("SELECT 2")[0]
    tokens = list(stmt.flatten())

    select_tok = tokens[0]
    assert select_tok.ttype is T.Keyword.DML
    assert _repr_cls(select_tok) == "DML"

    number_tok = next(t for t in tokens if t.ttype is T.Number.Integer)
    assert _repr_cls(number_tok) == "Integer"


def test_token_repr_single_quoted_string():
    # A single-quoted literal is tokenized as String.Single; repr() should
    # report "Single" (the leaf type), not "String" (the parent type).
    stmt = sqlparse.parse("'abc'")[0]
    tok = next(stmt.flatten())
    assert tok.ttype is T.String.Single
    assert _repr_cls(tok) == "Single"


def test_pprint_tree_shows_leaf_type_names():
    # TokenList._pprint_tree relies on the same leaf-type logic as
    # Token.__repr__ for the printed column, and must show "DML" /
    # "Integer" rather than "Keyword" / "Number".
    stmt = sqlparse.parse("SELECT 2")[0]
    out = io.StringIO()
    stmt._pprint_tree(f=out)

    expected = (
        "|- 0 DML 'SELECT'\n"
        "|- 1 Whitespace ' '\n"
        "`- 2 Integer '2'\n"
    )
    assert out.getvalue() == expected
