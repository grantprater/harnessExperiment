"""Regression test reproducing the sqlparse statement-splitting crash.

Bug report: sqlparse raises
    TypeError: unsupported operand type(s) for +=: 'NoneType' and 'int'
while processing ordinary SQL. Because the failing code lives in
``StatementSplitter``, which is used by every entry point of the library
(``sqlparse.parse``, ``sqlparse.format``, ``sqlparse.split`` and therefore
the CLI and ``formatter.validate_options`` based pipelines), the crash
shows up across many unrelated looking checks: plain option validation,
the ``sqlformat`` CLI with ``--in-place`` and multiple files, and simply
formatting a normal, harmless SQL statement.

These are exactly the three examples named in the report:
  * 'valid args'
  * 'cli multiple files with inplace'
  * 'do sprevention: normal sql still works' (DoS-prevention change did not
    break parsing of normal SQL)

The expected values below come directly from documented/intended behaviour:
  * ``formatter.validate_options`` is documented to accept normal keyword
    arguments (e.g. ``reindent=True``) and return a dict usable by
    ``build_filter_stack`` -- it must not raise and must not mutate valid
    input into something unusable.
  * The CLI's own ``--in-place``/``--help`` documentation states multiple
    files are supported together with ``--in-place``. The command must
    exit 0 and overwrite the files with formatted SQL.
  * ``sqlparse.format``/``sqlparse.parse`` are documented to work on any
    syntactically normal SQL statement (see README/intro.rst); a simple
    ``SELECT`` statement must parse and format successfully, unaffected by
    the CWE-1333 DoS-prevention fix mentioned in the CHANGELOG.
"""

import sqlparse
from sqlparse import cli


def test_valid_args():
    # A normal, well-formed set of formatting options must validate
    # successfully and keep working end to end.
    options = sqlparse.formatter.validate_options(
        {"reindent": True, "keyword_case": "upper"}
    )
    assert options["reindent"] is True
    assert options["keyword_case"] == "upper"

    # And the validated options must be usable to actually format SQL.
    result = sqlparse.format("select * from foo", **options)
    assert "SELECT" in result


def test_cli_multiple_files_with_inplace(tmp_path):
    file1 = tmp_path / "a.sql"
    file2 = tmp_path / "b.sql"
    file1.write_text("select * from foo;\n")
    file2.write_text("select * from bar;\n")

    exit_code = cli.main(["--in-place", str(file1), str(file2)])

    assert exit_code == 0
    assert "SELECT" in file1.read_text()
    assert "SELECT" in file2.read_text()


def test_dos_prevention_normal_sql_still_works():
    # A perfectly ordinary statement must parse and format without error;
    # the DoS-prevention (recursion/token limits) is only meant to trigger
    # on pathological input, not on everyday SQL.
    sql = "SELECT id, name FROM users WHERE active = 1 ORDER BY id;"

    statements = sqlparse.parse(sql)
    assert len(statements) == 1
    assert statements[0].get_type() == "SELECT"

    formatted = sqlparse.format(sql, reindent=True, keyword_case="upper")
    assert "SELECT" in formatted
    assert "FROM" in formatted
