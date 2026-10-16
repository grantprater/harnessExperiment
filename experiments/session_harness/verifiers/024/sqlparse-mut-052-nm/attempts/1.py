"""Regression tests for sqlparse grouping of function calls.

These reproduce the reported regression affecting two previously-passing
behaviours:

* "qualified function": a dotted/qualified function call such as
  ``foo.bar(1, 2)`` must still be recognised as a ``sql.Function`` *and*
  the whole expression must be grouped into a single ``sql.Identifier``
  (exactly as an unqualified function call like ``bar(1, 2)`` would be),
  so that ``get_real_name()``/``get_parent_name()`` behave as documented
  in ``sqlparse.sql.NameAliasMixin.get_real_name`` ("a.b.c -> real name
  is the component after the *last* dot") and
  ``sqlparse.sql.TokenList.get_parent_name`` ("A parent object is
  identified by the first occurring dot.").

* "aliased function without as": a function call directly followed by
  an alias name with no ``AS`` keyword in between (e.g. ``foo() bar``)
  must be grouped into a single ``sql.Identifier`` containing the
  ``sql.Function`` plus the alias, as documented in
  ``sqlparse.sql.NameAliasMixin.get_alias`` ("name alias" case).

Both scenarios are simple, well established sqlparse behaviours (the
very same style of statements are used throughout sqlparse's own
documentation and docstrings for ``get_real_name``/``get_parent_name``/
``get_alias``); they are not edge cases invented for this test.
"""

import sqlparse
from sqlparse import sql


def _find(token, cls):
    """Depth-first search for the first token instance of *cls*.

    Returns ``None`` if no such token is found anywhere in the token
    tree rooted at *token* (inclusive).
    """
    if isinstance(token, cls):
        return token
    if getattr(token, "is_group", False):
        for child in token.tokens:
            found = _find(child, cls)
            if found is not None:
                return found
    return None


def test_qualified_function_is_grouped_with_parent_identifier():
    stmt = sqlparse.parse("SELECT foo.bar(1, 2) FROM dual")[0]

    identifier = _find(stmt, sql.Identifier)
    assert identifier is not None, (
        "'foo.bar(1, 2)' should be grouped into a sql.Identifier, just "
        "like an unqualified function call would be"
    )

    func = _find(identifier, sql.Function)
    assert func is not None, (
        "qualifying the function name with 'foo.' must not prevent "
        "'bar(1, 2)' from being recognised as a sql.Function"
    )

    # NameAliasMixin.get_real_name(): "a.b.c -> real name is the
    # component after the *last* dot"
    assert func.get_real_name() == "bar"
    assert identifier.get_real_name() == "bar"

    # TokenList.get_parent_name(): "A parent object is identified by
    # the first occurring dot."
    assert identifier.get_parent_name() == "foo"


def test_aliased_function_without_as():
    stmt = sqlparse.parse("SELECT foo() bar FROM dual")[0]

    identifier = _find(stmt, sql.Identifier)
    assert identifier is not None, (
        "'foo() bar' should be grouped into a single sql.Identifier "
        "even though there is no explicit AS keyword"
    )

    func = _find(identifier, sql.Function)
    assert func is not None, (
        "the aliased expression must still contain a sql.Function for "
        "'foo()'"
    )
    assert func.get_real_name() == "foo"

    # NameAliasMixin.get_alias(): "name alias" (without AS) must be
    # recognised as the alias.
    assert identifier.get_alias() == "bar"
    assert identifier.get_real_name() == "foo"
    assert identifier.get_name() == "bar"
