"""Regression test for the inverted case-check in sqlparse.filters.tokens._CaseFilter.

sqlparse.filters.tokens._CaseFilter.process() currently reads:

    if not (ttype in self.ttype):
        value = self.convert(value)

which converts the case of every token whose type is *not* the filter's
target type, and leaves tokens of the target type untouched. For
KeywordCaseFilter (ttype = T.Keyword) this means keywords are left as-is
while everything else (identifiers, psql "\\command" tokens, punctuation,
etc.) gets case-converted -- exactly backwards from the documented and
intended behaviour (see README.rst quick-start example and the
`keyword_case` option documented in docs/source/api.rst: "Changes how
keywords are formatted"). This bug breaks any formatting call that uses
keyword_case, including the CLI's --in-place mode and formatting of psql
meta-commands such as "\\copy" (issue469: "Avoid formatting of psql
commands").
"""
import sqlparse
from sqlparse import cli


def test_format_keywordcase():
    # Documented behaviour (README.rst quick start): keywords get
    # case-converted, identifiers are left untouched.
    sql = 'select * from foo'
    formatted = sqlparse.format(sql, keyword_case='upper')
    assert formatted == 'SELECT * FROM foo'


def test_issue469_copy_as_psql_command():
    # psql meta-commands (tokenized as Generic.Command, not Keyword) must
    # not be touched by keyword casing; genuine SQL keywords following the
    # command (e.g. TO, STDOUT) are still regular keywords and do get
    # case-converted.
    sql = '\\copy foo to stdout'
    formatted = sqlparse.format(sql, keyword_case='upper')
    assert formatted == '\\copy foo TO STDOUT'


def test_cli_single_file_inplace(tmp_path):
    sql_file = tmp_path / "query.sql"
    sql_file.write_text('select * from foo;\n', encoding='utf-8')

    exit_code = cli.main(['-k', 'upper', '--in-place', str(sql_file)])

    assert exit_code == 0
    # Keywords are upper-cased in place, the identifier "foo" is left alone.
    assert sql_file.read_text(encoding='utf-8') == 'SELECT * FROM foo;\n'
