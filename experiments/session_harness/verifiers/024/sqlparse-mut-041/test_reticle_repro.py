"""Regression tests for sqlparse's grouping engine.

sqlparse/engine/grouping.py relies on ``_group_matching`` to find and group
constructs such as CASE/END, IF/END IF, BEGIN/END, parentheses and square
brackets.  Whenever such a construct is *nested inside an already grouped
container of a different type* (the canonical example, called out directly
in the source comment, is a CASE expression living inside a Parenthesis),
``_group_matching`` has to recurse into that container to find it:

    if token.is_group and not isinstance(token, cls):
        # Check inside previously grouped (i.e. parenthesis) if group
        # of different type is inside (i.e., case).
        _group_matching(token, cls, depth + 1)
        continue

If that condition is accidentally inverted to ``isinstance(token, cls)``,
recursion into *other* group types effectively never happens (a token is
never already an instance of ``cls`` before it has been grouped), so a CASE
expression wrapped in parentheses is silently left ungrouped - its keywords
stay as bare ``Keyword`` tokens instead of being combined into a single
``sqlparse.sql.Case`` node. This is exactly the kind of DoS-protection
related change (the MAX_GROUPING_DEPTH feature added a ``depth`` parameter
to this same function) that could introduce such a regression.

These tests check that the documented/intended grouping behaviour still
holds, and that it continues to hold for inputs whose nesting depth stays
within the documented ``MAX_GROUPING_DEPTH`` cap, finishing quickly.
"""

import time

import sqlparse
from sqlparse import sql
from sqlparse.engine import grouping


def _find_first(tlist, cls):
    """Depth-first search for the first token of type *cls* in *tlist*."""
    for tok in tlist.tokens:
        if isinstance(tok, cls):
            return tok
        if tok.is_group:
            found = _find_first(tok, cls)
            if found is not None:
                return found
    return None


def test_case_expression_wrapped_in_parentheses_is_grouped_as_case():
    """A CASE...END expression nested inside parentheses must still be
    recognised and grouped as a single ``sqlparse.sql.Case`` instance.

    This mirrors the documented intent of ``_group_matching`` (see the
    comment "Check inside previously grouped (i.e. parenthesis) if group
    of different type is inside (i.e., case)" in
    sqlparse/engine/grouping.py): grouping for a given construct must
    recurse into *already grouped containers of other types* to find and
    group nested occurrences of that construct.
    """
    parsed = sqlparse.parse(
        "SELECT (CASE WHEN a = 1 THEN 2 ELSE 3 END) FROM t"
    )[0]

    paren = _find_first(parsed, sql.Parenthesis)
    assert paren is not None, "expected a Parenthesis group in the statement"

    case = _find_first(paren, sql.Case)
    assert case is not None, (
        "a CASE expression nested inside parentheses should be grouped "
        "into a sqlparse.sql.Case instance, not left as bare keywords"
    )

    # The Case node, once properly grouped, must behave like any other
    # Case node: get_cases() should report the WHEN branch and the ELSE
    # branch.
    cases = case.get_cases(skip_ws=True)
    assert len(cases) == 2
    condition, value = cases[0]
    assert condition and value  # WHEN a = 1 THEN 2
    else_condition, else_value = cases[1]
    assert else_condition is None
    assert else_value


def test_nested_parentheses_within_depth_cap_parse_quickly():
    """Legitimate, deeply (but not excessively) nested parentheses must
    keep parsing successfully and fast.

    ``MAX_GROUPING_DEPTH`` exists to reject pathological/adversarial input
    (see sqlparse/engine/grouping.py), not to slow down or break ordinary
    nested SQL that stays within the cap. Using a depth comfortably below
    the cap must neither raise nor take anywhere close to the ~10s+ CPU
    pinning described for the pre-fix quadratic behaviour.
    """
    depth = grouping.MAX_GROUPING_DEPTH - 10
    sql_text = "SELECT " + "(" * depth + "1" + ")" * depth

    start = time.perf_counter()
    result = sqlparse.parse(sql_text)
    elapsed = time.perf_counter() - start

    assert len(result) == 1
    assert elapsed < 1.0
