"""Regression test for the 'like and ilike comparison' bug.

sqlparse's keyword table (sqlparse/keywords.py) defines a single SQL_REGEX
rule:

    (r'(NOT\s+)?(LIKE|ILIKE|RLIKE)\b', tokens.Operator.Comparison)

so LIKE, ILIKE (and their NOT-prefixed forms) are intended to be tokenized
identically as ``tokens.Operator.Comparison`` and, consequently, grouped by
``sqlparse.engine.grouping.group_comparison`` into a single
``sqlparse.sql.Comparison`` node -- the same way any other comparison
operator (``=``, ``<``, ...) is grouped. This test checks that documented,
intended behavior for both LIKE and ILIKE (plain and NOT-prefixed).
"""
import sqlparse
from sqlparse import sql, tokens as T


def _get_single_comparison(statement_sql):
    """Parse statement_sql and return its single top-level Comparison token."""
    parsed = sqlparse.parse(statement_sql)[0]
    comparisons = [tok for tok in parsed.tokens
                   if isinstance(tok, sql.Comparison)]
    assert len(comparisons) == 1, (
        f"expected exactly one Comparison group in {statement_sql!r}, "
        f"got {comparisons!r} from tokens {parsed.tokens!r}"
    )
    return comparisons[0]


def test_like_comparison_is_grouped():
    cmp = _get_single_comparison("foo LIKE 'bar'")
    # the LIKE operator token itself must be classified as a comparison
    # operator, per the SQL_REGEX rule in keywords.py
    op_idx, op_tok = cmp.token_next_by(t=T.Operator.Comparison)
    assert op_tok is not None
    assert op_tok.ttype is T.Operator.Comparison
    assert op_tok.normalized.upper() == 'LIKE'


def test_ilike_comparison_is_grouped():
    # ILIKE must behave exactly like LIKE: a single Comparison group whose
    # operator token has ttype Operator.Comparison.
    cmp = _get_single_comparison("foo ILIKE 'bar'")
    op_idx, op_tok = cmp.token_next_by(t=T.Operator.Comparison)
    assert op_tok is not None
    assert op_tok.ttype is T.Operator.Comparison
    assert op_tok.normalized.upper() == 'ILIKE'


def test_not_like_and_not_ilike_comparison_are_grouped():
    for operator in ('NOT LIKE', 'NOT ILIKE'):
        cmp = _get_single_comparison(f"foo {operator} 'bar'")
        op_idx, op_tok = cmp.token_next_by(t=T.Operator.Comparison)
        assert op_tok is not None, f"no comparison operator token for {operator!r}"
        assert op_tok.ttype is T.Operator.Comparison
        assert op_tok.normalized.upper() == operator


def test_like_and_ilike_produce_same_grouping_shape():
    # LIKE and ILIKE must produce structurally equivalent Comparison groups
    # (same number of child tokens), since they are meant to be handled by
    # the exact same tokenizing/grouping rule.
    like_cmp = _get_single_comparison("foo LIKE 'bar'")
    ilike_cmp = _get_single_comparison("foo ILIKE 'bar'")
    assert len(like_cmp.tokens) == len(ilike_cmp.tokens)
