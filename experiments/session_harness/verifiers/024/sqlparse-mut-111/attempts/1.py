import sqlparse
from sqlparse import sql


def _first_function(sql_text):
    """Parse sql_text and return the first sql.Function token found."""
    parsed = sqlparse.parse(sql_text)[0]
    func = parsed.token_next_by(i=sql.Function)[1]
    assert func is not None, "expected statement to contain a Function token"
    return func


def test_grouping_function():
    # "foo()" must be grouped into a single sql.Function token.
    func = _first_function('foo()')
    assert isinstance(func, sql.Function)
    assert func.get_name() == 'foo'


def test_parse_function_param_single_literal():
    # A function called with a single literal argument must report that
    # literal as its only parameter.
    func = _first_function('foo(5)')
    params = list(func.get_parameters())
    assert len(params) == 1
    assert params[0].value == '5'


def test_parse_function_parameter():
    # A function called with several arguments must report all of them,
    # in order, via get_parameters().
    func = _first_function('foo(1, 2)')
    params = list(func.get_parameters())
    assert len(params) == 2
    assert [p.value for p in params] == ['1', '2']
