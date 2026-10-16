import sqlparse
from sqlparse import sql


def test_grouping_function():
    """A name immediately followed by a parenthesized argument list must be
    grouped into a single sql.Function token.

    ``sql.Function`` is documented as "A function or procedure call", and
    grouping must be lossless: converting the parsed statement back to a
    string with str() must reproduce the original SQL exactly (this
    round-trip guarantee is the core documented behaviour of sqlparse).
    """
    original = 'foo(1, 2)'
    parsed = sqlparse.parse(original)[0]

    assert len(parsed.tokens) == 1
    assert isinstance(parsed.tokens[0], sql.Function)
    assert str(parsed) == original


def test_grouping_identifier_function():
    """``foo() AS bar`` must be grouped into an Identifier wrapping a
    Function, exposing the correct real name and alias (as documented by
    Identifier.get_real_name/get_alias and Function's docstring), and the
    statement must round-trip losslessly through str().
    """
    original = 'SELECT foo(1) AS bar'
    parsed = sqlparse.parse(original)[0]

    identifier = parsed.tokens[-1]
    assert isinstance(identifier, sql.Identifier)
    assert isinstance(identifier.tokens[0], sql.Function)
    assert identifier.get_real_name() == 'foo'
    assert identifier.get_alias() == 'bar'
    assert str(parsed) == original


def test_grouping_function_list():
    """Multiple function calls in a comma separated list must each be
    grouped into sql.Function tokens inside a single sql.IdentifierList,
    and the whole statement must still round-trip losslessly through
    str() -- this exercises the repeated/extended grouping path used for
    wide column lists.
    """
    original = 'SELECT foo(1), bar(2), baz(3)'
    parsed = sqlparse.parse(original)[0]

    identifier_list = parsed.tokens[-1]
    assert isinstance(identifier_list, sql.IdentifierList)
    functions = [t for t in identifier_list.tokens if isinstance(t, sql.Function)]
    assert len(functions) == 3
    assert [f.get_real_name() for f in functions] == ['foo', 'bar', 'baz']
    assert str(parsed) == original
