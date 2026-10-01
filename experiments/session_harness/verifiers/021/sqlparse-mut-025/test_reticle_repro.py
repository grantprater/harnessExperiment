"""Regression test for issue672: deep/shallow-copying sqlparse tokens must
not raise ``TypeError: '_TokenType' object is not callable``.

``sqlparse.tokens._TokenType`` implements a "lazy" ``__getattr__`` that
creates and caches new token sub-types on first attribute access (e.g.
``Token.Keyword.DML``). Because ``copy.copy``/``copy.deepcopy`` probe for
optional dunder hooks such as ``__copy__``/``__deepcopy__``/``__reduce_ex__``
via ``getattr(obj, name, None)``, a ``__getattr__`` that does not special
case dunder names will happily manufacture a bogus ``_TokenType`` instance
for e.g. ``__deepcopy__`` instead of raising ``AttributeError``. ``copy``
then treats that manufactured (non-callable) tuple as the hook and calls
it, raising ``TypeError: '_TokenType' object is not callable``.

This was originally fixed for issue672 ("Ignore dunder attributes when
creating Tokens") and the fix has regressed.
"""
import copy

import pytest

import sqlparse
from sqlparse.tokens import Keyword, Token


def test_tokentype_dunder_attribute_access_raises_attributeerror():
    """Accessing a dunder attribute on a _TokenType must raise
    AttributeError instead of silently creating a new bogus token type.

    This is the underlying contract that copy/pickle/etc rely on via
    getattr(obj, "__dunder__", None).
    """
    with pytest.raises(AttributeError):
        Keyword.__deepcopy__

    with pytest.raises(AttributeError):
        Token.__copy__


def test_copy_tokentype_does_not_raise():
    """copy.copy()/copy.deepcopy() on a token type must work and return
    an equal token type, not raise TypeError.
    """
    copied = copy.copy(Keyword)
    assert copied == Keyword

    deep_copied = copy.deepcopy(Keyword)
    assert deep_copied == Keyword


def test_deepcopy_parsed_statement_issue672():
    """Deep-copying a parsed Statement (the scenario from issue672) must
    succeed and produce an independent, but textually identical, copy.
    """
    sql = "SELECT * FROM foo WHERE id = 1"
    statement = sqlparse.parse(sql)[0]

    copied_statement = copy.deepcopy(statement)

    # The copy renders identically to the original.
    assert str(copied_statement) == str(statement) == sql

    # It really is a separate object graph, not the same instance.
    assert copied_statement is not statement
    assert copied_statement.tokens is not statement.tokens

    # Mutating the copy's token list must not affect the original.
    copied_statement.tokens.pop()
    assert len(copied_statement.tokens) != len(statement.tokens)
