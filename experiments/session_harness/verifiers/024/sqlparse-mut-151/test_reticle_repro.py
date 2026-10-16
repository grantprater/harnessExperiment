import sqlparse


def test_output_format_php_multiline_statement():
    """Formatting a multi-line statement with output_format='php' must not
    raise an IndexError, and must emit valid PHP that assigns the first
    line with '=' and appends each subsequent line with '.=', mirroring
    the already-correct behaviour of OutputPythonFilter for the 'python'
    output format (sqlparse/filters/output.py). The PHP filter builds the
    continuation header to be the same width as the leading quote on the
    first line (extra space before '=' to match '.=' on later lines), so
    both quotes line up in column 8.
    """
    sql = 'select *\nfrom foo'

    result = sqlparse.format(sql, output_format='php')

    assert result == '$sql  = "select * ";\n$sql .= "from foo";'


def test_output_format_php_single_line_statement_unaffected():
    """A single-line statement has no embedded newline, so it must keep
    producing the simple '$var = "...";' assignment exactly as before;
    this guards the fix for the multi-line case against regressing the
    already-working single-line behaviour.
    """
    sql = 'select * from foo'

    result = sqlparse.format(sql, output_format='php')

    assert result == '$sql = "select * from foo";'
