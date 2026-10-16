"""
Regression test for sqlparse.sql.NameAliasMixin.get_real_name().

sql.NameAliasMixin.get_real_name() is documented (see its own docstring and
the docstring of Identifier) to return the *real* (object) name of an
identifier, i.e. the name before any "AS alias" or implicit "name alias"
part, and - for dotted names like "a.b.c" - the component after the last
dot.

The current implementation computes the position of the relevant dot with:

    dot_idx = None
    for idx, tok in enumerate(self.tokens):
        if not (tok.match(T.Punctuation, '.')):
            dot_idx = idx

which keeps overwriting ``dot_idx`` for every token that is *not* a dot,
so it ends up pointing at the *last* token in the identifier (typically the
alias) instead of at the last top-level dot (or ``None`` when there is no
top-level dot at all). As a result, ``get_real_name()`` incorrectly returns
the alias instead of the real name whenever an identifier carries an alias
(with or without the ``AS`` keyword).
"""
import sqlparse
from sqlparse import sql


def test_real_name_for_identifier_aliased_without_as():
    # "foo bar" -> real name is "foo", alias is "bar".
    statement = sqlparse.parse('foo bar')[0]
    identifier = statement.tokens[0]
    assert isinstance(identifier, sql.Identifier)

    assert identifier.get_alias() == 'bar'
    # This is the part that the regression breaks: get_real_name()
    # currently returns 'bar' (the alias) instead of 'foo'.
    assert identifier.get_real_name() == 'foo'
    assert identifier.get_name() == 'bar'


def test_real_name_for_dotted_identifier_with_as_alias():
    # "foo.bar AS baz" -> parent name "foo", real name "bar", alias "baz".
    statement = sqlparse.parse('foo.bar AS baz')[0]
    identifier = statement.tokens[0]
    assert isinstance(identifier, sql.Identifier)

    assert identifier.get_parent_name() == 'foo'
    assert identifier.get_alias() == 'baz'
    # Regression: currently returns 'baz' (the alias) instead of 'bar'.
    assert identifier.get_real_name() == 'bar'


def test_real_name_for_simple_identifier_without_alias():
    # Sanity/regression guard: a plain identifier with no dot and no alias
    # must keep working exactly as before the fix.
    statement = sqlparse.parse('foo')[0]
    identifier = statement.tokens[0]
    assert isinstance(identifier, sql.Identifier)

    assert identifier.get_alias() is None
    assert identifier.get_real_name() == 'foo'
    assert identifier.get_name() == 'foo'
