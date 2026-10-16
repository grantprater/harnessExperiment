"""Regression test for the 'grouping create table' bug.

Reported symptom: for a statement like

    CREATE TABLE db.tbl (a string)

the table name identifier ends up including the column-definition
parenthesis, producing 'db.tbl (a string)' instead of the correct
'db.tbl', because ``group_functions`` grouped the table name together
with the following parenthesis as if it were a function call.

The parenthesis that follows a table name in ``CREATE TABLE ...`` (without
an ``AS`` clause) holds column definitions, not function arguments, and
must stay a separate, directly reachable token -- see
examples/column_defs_lowlevel.py, which relies on
``statement.token_next_by(i=sqlparse.sql.Parenthesis)`` finding the column
definitions as a top-level token of the statement.
"""

import sqlparse
from sqlparse import sql, tokens as T


def _table_name_token(statement):
    """Return the token directly following the TABLE keyword."""
    idx, _ = statement.token_next_by(m=(T.Keyword, 'TABLE'))
    assert idx is not None
    _, token = statement.token_next(idx)
    return token


def test_create_table_name_does_not_include_column_definitions():
    stmt = sqlparse.parse('create table db.tbl (a string)')[0]
    name_token = _table_name_token(stmt)
    assert str(name_token) == 'db.tbl'


def test_create_table_column_parenthesis_is_a_separate_top_level_token():
    stmt = sqlparse.parse('create table db.tbl (a string)')[0]
    idx, paren = stmt.token_next_by(i=sql.Parenthesis)
    assert paren is not None
    assert str(paren) == '(a string)'
    # the parenthesis must not have been swallowed into the name token
    name_token = _table_name_token(stmt)
    assert paren is not name_token
    assert 'a string' not in str(name_token)


def test_create_table_without_schema_qualifier():
    stmt = sqlparse.parse('create table tbl (a string)')[0]
    name_token = _table_name_token(stmt)
    assert str(name_token) == 'tbl'


def test_create_table_statement_round_trips():
    original = 'create table db.tbl (a string)'
    stmt = sqlparse.parse(original)[0]
    assert str(stmt) == original
