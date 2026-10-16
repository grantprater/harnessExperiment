"""Regression tests for sqlparse's handling of ``AS`` aliasing.

These correspond to the library's historically documented behaviour
(see CHANGELOG entries about "Fix handling of NULL keywords in aliased
identifiers" and "Fix a bug where keywords were identified as aliased
identifiers"):

* ``NULL AS x`` must be grouped into a single ``Identifier`` (NULL is the
  one keyword that is explicitly allowed to be used as the left-hand side
  of an alias).
* Ordinary keywords (e.g. ``DISTINCT``) must *not* be swallowed into an
  alias ``Identifier`` just because they happen to sit in front of an
  ``AS ...`` clause.

A single-character regression in ``sqlparse.engine.grouping.group_as``
(``!=`` instead of ``==`` when comparing the previous token's normalized
value against ``'NULL'``) flips both of these behaviours at once: NULL
stops being aliased, while arbitrary keywords start being aliased.
"""
import pytest

import sqlparse
from sqlparse import sql
from sqlparse import tokens as T


def test_null_with_as():
    # Make sure "NULL" and "AS" are grouped together into a single
    # Identifier, exactly like any other expression followed by AS.
    p = sqlparse.parse('NULL AS c1')[0]

    assert len(p.tokens) == 1
    assert isinstance(p.tokens[0], sql.Identifier)
    assert p.tokens[0].get_alias() == 'c1'


def test_dont_alias_keywords():
    # A bare keyword (other than NULL) sitting in front of "AS ..." must
    # not be grouped into an alias Identifier together with it.
    p = sqlparse.parse('DISTINCT AS c1')[0]

    first = p.tokens[0]
    assert not isinstance(first, sql.Identifier)
    assert first.ttype is T.Keyword
    assert first.normalized == 'DISTINCT'

    # the real identifier "c1" is unaffected and still parses as such
    identifiers = [tok for tok in p.tokens if isinstance(tok, sql.Identifier)]
    assert len(identifiers) == 1
    assert identifiers[0].get_real_name() == 'c1'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
