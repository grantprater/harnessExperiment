"""
Regression test for sqlparse's ``reindent_aligned`` formatting option.

These tests pin down the *exact* text produced by
``sqlparse.filters.aligned_indent.AlignedIndentFilter`` for three cases
mentioned in the bug report: a basic SELECT/FROM/WHERE/AND query, a CASE
statement, and a CASE statement whose WHEN-condition contains a BETWEEN
... AND ... clause.

The expected strings are derived directly from the algorithm documented
in ``aligned_indent.py``:

* ``nl()`` builds each line's leading whitespace as
  ``self._max_kwd_len + offset + indent*unit + self.offset`` where
  ``_max_kwd_len == len('select') == 6``. For top-level split keywords
  (FROM/WHERE/AND/...) offset is ``-len(keyword)``, so every such
  keyword's last character lands on column 6 (right-aligned under
  "select"). Continuation columns in an identifier list use
  ``nl(1)`` -> 7 leading spaces (``len('select ')``), as stated in the
  "offset = 1 represent a single space after SELECT" comment.

* ``_process_case`` right-aligns WHEN/ELSE/END so they all end on column
  ``len('select') + len('case ') + len('when ') == 16`` -- a direct
  consequence of ``offset_ - len(str(stmt))`` where ``stmt`` is the
  WHEN/ELSE/END keyword token itself (the first element collected by
  ``Case.get_cases``). Condition padding aligns the following ``THEN``
  column across WHEN-clauses of different condition width.

* The final ``SerializerUnicode`` postprocessing step right-strips every
  output line, so any trailing whitespace left before an inserted
  newline token does not show up in the final string.

A regression broke this alignment; the tests below fail while the bug
is present and pass again once the correct alignment/text is restored.
"""
import sqlparse


def test_reindent_aligned_basic():
    sql = "select a, b, c from thetable where x = 1 and y = 2"
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = (
        "select a,\n"
        "       b,\n"
        "       c\n"
        "  from thetable\n"
        " where x = 1\n"
        "   and y = 2"
    )
    assert formatted == expected


def test_reindent_aligned_case_statement():
    sql = "SELECT CASE WHEN a = 1 THEN 'x' WHEN bb = 2 THEN 'y' ELSE 'z' END"
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = (
        "SELECT CASE WHEN a = 1  THEN 'x'\n"
        "            WHEN bb = 2 THEN 'y'\n"
        "            ELSE 'z'\n"
        "             END"
    )
    assert formatted == expected


def test_reindent_aligned_case_statement_with_between():
    sql = (
        "SELECT CASE WHEN a BETWEEN 1 AND 2 THEN 'x' "
        "WHEN a BETWEEN 3 AND 4 THEN 'y' END"
    )
    formatted = sqlparse.format(sql, reindent_aligned=True)

    expected = (
        "SELECT CASE WHEN a BETWEEN 1 AND 2 THEN 'x'\n"
        "            WHEN a BETWEEN 3 AND 4 THEN 'y'\n"
        "             END"
    )
    assert formatted == expected
