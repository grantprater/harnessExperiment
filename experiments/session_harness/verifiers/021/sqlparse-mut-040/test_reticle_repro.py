import sqlparse


def test_output_format_python_single_statement():
    # A single formatted statement should NOT start with a leading newline;
    # the assignment line should begin directly with the variable name.
    sql = 'select * from foo;'
    formatted = sqlparse.format(sql, output_format='python')
    assert formatted == "sql = 'select * from foo;'"


def test_output_format_python_multiple_statements():
    # For multiple statements, only statements after the first should be
    # preceded by a newline (mirrors the PHP output filter's behaviour,
    # and the documented output format for the `python` formatter).
    sql = 'select * from foo; select * from bar;'
    formatted = sqlparse.format(sql, output_format='python')
    expected = "sql = 'select * from foo;'\nsql2 = 'select * from bar;'"
    assert formatted == expected
