import sqlparse
from sqlparse.sql import Identifier


def _get_identifier(sql):
    """Parse sql and return the first Identifier token found."""
    parsed = sqlparse.parse(sql)[0]
    _, identifier = parsed.token_next_by(i=Identifier)
    assert identifier is not None, f"no Identifier found in {sql!r}"
    return identifier


def _index_values(identifier):
    """Collapse each yielded token list from get_array_indices() into a string."""
    return [''.join(tok.value for tok in index)
            for index in identifier.get_array_indices()]


def test_simple_1d_array_index():
    # "foo[1]" must group into a single Identifier containing the Name
    # and a SquareBrackets group; get_array_indices() must yield the
    # contents of that SquareBrackets group (i.e. the index expression).
    identifier = _get_identifier("SELECT foo[1] FROM bar")
    assert _index_values(identifier) == ['1']


def test_2d_array_index():
    # "foo[1][2]" groups both SquareBrackets into the same flat
    # Identifier; get_array_indices() must yield one entry per
    # dimension, in order.
    identifier = _get_identifier("SELECT foo[1][2] FROM bar")
    assert _index_values(identifier) == ['1', '2']


def test_schema_qualified_array_index():
    # "myschema.foo[1]" is grouped (via group_period/group_arrays) into
    # a single flat Identifier: Name, '.', Name, SquareBrackets.
    # get_array_indices() must still yield only the index expression.
    identifier = _get_identifier("SELECT myschema.foo[1] FROM bar")
    assert _index_values(identifier) == ['1']


def test_array_index_with_expression():
    # The index itself can be a multi-token expression; the full
    # expression (minus the surrounding brackets) must be returned.
    identifier = _get_identifier("SELECT foo[1+2] FROM bar")
    assert _index_values(identifier) == ['1+2']
