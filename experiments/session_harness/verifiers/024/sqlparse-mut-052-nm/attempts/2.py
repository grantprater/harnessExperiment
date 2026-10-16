"""Regression tests for sqlparse grouping of function calls.

These reproduce the reported regression affecting two previously-passing
behaviours of sqlparse's grouping engine:

* "qualified function": a dotted/qualified function call such as
  ``foo.bar(5)`` must be recognised as a single ``sql.Identifier`` that
  wraps the qualifier, the dot and the ``sql.Function`` call, exactly as
  an unqualified function call would be wrapped. This is the documented
  behaviour of ``sqlparse.sql.NameAliasMixin.get_real_name`` ("a.b.c ->
  real name is the component after the *last* dot") and
  ``sqlparse.sql.TokenList.get_parent_name`` ("A parent object is
  identified by the first occurring dot."): for these methods to return
  anything sensible, the dotted expression must be grouped as a single
  Identifier containing exactly the qualifier, the dot and the function.

* "aliased function without as": a function call directly followed by
  an alias name with no ``AS`` keyword in between (e.g. ``foo() bar``)
  must be grouped into a single ``sql.Identifier`` containing the
  ``sql.Function`` plus the alias, as documented in
  ``sqlparse.sql.NameAliasMixin.get_alias`` ("name alias" case, i.e.
  "name alias" or "complicated column expression alias").

Both statements are parsed as standalone top-level statements (mirroring
how this is exercised in sqlparse's own grouping tests) so that the
whole statement is expected to collapse into exactly one top-level
token: the Identifier. This stricter, structural expectation makes the
test sensitive to grouping regressions that leave the function call and
its qualifier/alias as separate, unmerged top-level tokens.
"""

import sqlparse
from sqlparse import sql


def test_qualified_function_is_grouped_as_single_identifier():
    stmt = sqlparse.parse('foo.bar(5)')[0]

    # The whole dotted function call must collapse into exactly one
    # top-level token: a sql.Identifier wrapping 'foo', '.', and the
    # sql.Function for 'bar(5)'.
    assert len(stmt.tokens) == 1, (
        "'foo.bar(5)' should be fully grouped into a single top-level "
        f"token, got {len(stmt.tokens)}: {stmt.tokens!r}"
    )

    identifier = stmt.tokens[0]
    assert isinstance(identifier, sql.Identifier), (
        "qualifying the function name with 'foo.' must not prevent the "
        "whole expression from being grouped into a sql.Identifier, "
        f"got {type(identifier).__name__} instead"
    )

    func = identifier.token_next_by(i=sql.Function)[1]
    assert func is not None, (
        "the sql.Identifier for 'foo.bar(5)' must contain a sql.Function "
        "for 'bar(5)'"
    )

    # NameAliasMixin.get_real_name(): "a.b.c -> real name is the
    # component after the *last* dot"
    assert identifier.get_real_name() == 'bar'

    # TokenList.get_parent_name(): "A parent object is identified by
    # the first occurring dot."
    assert identifier.get_parent_name() == 'foo'


def test_aliased_function_without_as_is_grouped_as_single_identifier():
    stmt = sqlparse.parse('foo() bar')[0]

    # The function call plus its alias must collapse into exactly one
    # top-level token: a sql.Identifier.
    assert len(stmt.tokens) == 1, (
        "'foo() bar' should be fully grouped into a single top-level "
        f"token, got {len(stmt.tokens)}: {stmt.tokens!r}"
    )

    identifier = stmt.tokens[0]
    assert isinstance(identifier, sql.Identifier), (
        "a function call followed directly by an alias (no AS) must be "
        f"grouped into a sql.Identifier, got {type(identifier).__name__} "
        "instead"
    )

    func = identifier.token_next_by(i=sql.Function)[1]
    assert func is not None, (
        "the aliased expression must still contain a sql.Function for "
        "'foo()'"
    )
    assert func.get_real_name() == 'foo'

    # NameAliasMixin.get_alias(): "name alias" (without AS) must be
    # recognised as the alias.
    assert identifier.get_alias() == 'bar'
    assert identifier.get_real_name() == 'foo'
    assert identifier.get_name() == 'bar'
