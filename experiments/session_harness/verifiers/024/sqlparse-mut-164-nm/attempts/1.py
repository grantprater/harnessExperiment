"""
Regression test for sqlparse's TokenList.get_parent_name().

The method's docstring says:
    "Return name of the parent object if any.
     A parent object is identified by the first occurring dot."

So for an identifier like ``foo.bar`` (or a qualified function call like
``foo.bar()``), ``get_parent_name()`` must return ``'foo'``, and for a plain,
unqualified identifier (no dot at all) it must return ``None`` (not raise).

The currently installed version of ``sqlparse.sql.TokenList.get_parent_name``
has its return logic inverted:

    return None if prev_ is not None else remove_quotes(prev_.value)

which does the exact opposite of the documented behavior: it returns
``None`` whenever there *is* a token before the dot (the real qualifying
case), and tries to call ``.value`` on ``None`` whenever there is *no* dot
at all (raising ``AttributeError`` instead of returning ``None``).  This is
the root cause behind the reported regression affecting qualified-name /
qualified-function grouping behaviour.
"""
import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Identifier, Token


def test_get_parent_name_returns_qualifying_identifier():
    """'foo.bar' -> parent name of the qualified identifier is 'foo'."""
    ident = Identifier([
        Token(T.Name, 'foo'),
        Token(T.Punctuation, '.'),
        Token(T.Name, 'bar'),
    ])

    assert ident.get_parent_name() == 'foo'


def test_get_parent_name_without_dot_is_none():
    """An unqualified identifier has no parent, so this must be None,
    not raise an AttributeError."""
    ident = Identifier([Token(T.Name, 'foo')])

    assert ident.get_parent_name() is None


def test_qualified_function_parent_name():
    """Parsing 'foo.bar()' should group 'foo.bar()' into a single
    Identifier whose parent name is 'foo' and whose real name is 'bar',
    matching the 'qualified function' behaviour reported as regressed."""
    parsed = sqlparse.parse('foo.bar()')[0]
    ident = parsed.tokens[0]

    assert isinstance(ident, Identifier)
    assert ident.get_real_name() == 'bar'
    assert ident.get_parent_name() == 'foo'
