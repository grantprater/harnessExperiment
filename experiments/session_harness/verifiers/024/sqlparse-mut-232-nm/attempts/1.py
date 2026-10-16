"""
Regression test for sqlparse's ``reindent_aligned`` formatting option.

These tests check the alignment invariants that
``sqlparse.filters.aligned_indent.AlignedIndentFilter`` is designed to
produce, as documented directly in that module:

* ``nl()`` builds each line's leading whitespace as
  ``self._max_kwd_len + offset + indent*unit + self.offset`` characters,
  where ``_max_kwd_len == len('select')`` (6).  For top level split
  keywords (``FROM``, ``WHERE``, ``AND``, ...) ``offset`` is
  ``-len(keyword)``, so every such keyword's *last* character lands on
  column 6 -- i.e. keywords are right-aligned under "SELECT".

* Likewise columns in an identifier list are indented to align under the
  first selected column, i.e. ``len('select ')`` == 7 spaces (see the
  comment "offset = 1 represent a single space after SELECT" in
  ``AlignedIndentFilter.nl``).

* ``_process_case`` aligns ``WHEN``/``ELSE``/``END`` of a ``CASE``
  expression so that they all end on the same column, namely
  ``len('select') + len('case ') + len('when ')`` == 16 (the column right
  after "SELECT CASE WHEN"), regardless of the individual keyword's
  length -- this is a direct consequence of the formula
  ``offset_ - len(str(stmt))`` used in ``_process_case``.

A regression broke this alignment behaviour; the tests below fail while
the bug is present and pass again once the correct alignment is
restored.
"""
import sqlparse


def _leading_spaces(line):
    return len(line) - len(line.lstrip(' '))


def test_reindent_aligned_basic_keyword_and_column_alignment():
    sql = "select a, b, c from thetable where x = 1 and y = 2"
    formatted = sqlparse.format(sql, reindent_aligned=True)
    lines = formatted.split('\n')

    # Continuation columns ("b", "c") must line up directly under the
    # first selected column ("a"), i.e. indented by len('select ') == 7
    # spaces.
    continuation_lines = [
        line for line in lines
        if line.lstrip(' ').startswith('b') or line.lstrip(' ').startswith('c')
    ]
    assert continuation_lines, f"no continuation column lines found in {lines!r}"
    for line in continuation_lines:
        assert _leading_spaces(line) == 7, (
            f"column continuation line {line!r} is not aligned under "
            f"the first selected column"
        )

    # FROM / WHERE / AND must be right-aligned so that their last
    # character lands on column 6 (the length of "select").
    keyword_lines = []
    for line in lines:
        stripped = line.lstrip(' ')
        word = stripped.split(' ', 1)[0] if stripped else ''
        if word.lower() in ('from', 'where', 'and'):
            keyword_lines.append((word, line))

    assert len(keyword_lines) == 3, (
        f"expected to find FROM/WHERE/AND keyword lines, got {lines!r}"
    )
    for word, line in keyword_lines:
        end_col = _leading_spaces(line) + len(word)
        assert end_col == 6, (
            f"keyword {word!r} in line {line!r} does not right-align "
            f"to column 6 (len('select'))"
        )


def test_reindent_aligned_case_statement_alignment():
    sql = "SELECT CASE WHEN a = 1 THEN 'x' WHEN bb = 2 THEN 'y' ELSE 'z' END"
    formatted = sqlparse.format(sql, reindent_aligned=True)
    lines = formatted.split('\n')

    assert lines[0].startswith("SELECT CASE WHEN"), lines

    # WHEN / ELSE / END must all be right-aligned to the column right
    # after "SELECT CASE WHEN" (i.e. len('select')+len('case ')+len('when ')
    # == 16), independently of the differing lengths of those keywords.
    base_col = len("SELECT CASE WHEN")

    keyword_lines = []
    for line in lines[1:]:
        stripped = line.lstrip(' ')
        word = stripped.split(' ', 1)[0] if stripped else ''
        if word in ('WHEN', 'ELSE', 'END'):
            keyword_lines.append((word, line))

    assert keyword_lines, f"expected WHEN/ELSE/END continuation lines, got {lines!r}"
    for word, line in keyword_lines:
        end_col = _leading_spaces(line) + len(word)
        assert end_col == base_col, (
            f"{word!r} in line {line!r} does not right-align to column "
            f"{base_col} together with the other CASE keywords"
        )


def test_reindent_aligned_case_statement_with_between_alignment():
    sql = (
        "SELECT CASE WHEN a BETWEEN 1 AND 2 THEN 'x' "
        "WHEN a BETWEEN 3 AND 4 THEN 'y' END"
    )
    formatted = sqlparse.format(sql, reindent_aligned=True)
    lines = formatted.split('\n')

    assert lines[0].startswith("SELECT CASE WHEN"), lines

    base_col = len("SELECT CASE WHEN")

    # The "AND" that is part of "BETWEEN x AND y" belongs to the
    # condition and must stay on the same line as its WHEN clause; only
    # WHEN/END are expected to start a new, aligned line.
    for line in lines[1:]:
        first_word = line.lstrip(' ').split(' ', 1)[0] if line.strip() else ''
        assert first_word != 'AND', (
            f"BETWEEN ... AND ... was incorrectly split across lines: {lines!r}"
        )

    keyword_lines = []
    for line in lines[1:]:
        stripped = line.lstrip(' ')
        word = stripped.split(' ', 1)[0] if stripped else ''
        if word in ('WHEN', 'END'):
            keyword_lines.append((word, line))

    assert keyword_lines, f"expected WHEN/END continuation lines, got {lines!r}"
    for word, line in keyword_lines:
        end_col = _leading_spaces(line) + len(word)
        assert end_col == base_col, (
            f"{word!r} in line {line!r} does not right-align to column "
            f"{base_col} when its condition contains BETWEEN ... AND ..."
        )
