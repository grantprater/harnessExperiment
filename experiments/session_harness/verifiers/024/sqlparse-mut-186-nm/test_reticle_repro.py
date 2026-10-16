import sqlparse


def test_issue193_splitting_function():
    """A CREATE FUNCTION whose body is a BEGIN...END block must be treated
    as a single statement, and whatever statement follows it must start a
    new one. The semicolon that terminates the function (after the final
    END) is the one that should trigger the split, not any semicolon
    appearing inside the BEGIN...END body.
    """
    sql = (
        "CREATE FUNCTION f1() RETURNS INT\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "END;\n"
        "SELECT 2;"
    )
    statements = sqlparse.split(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE FUNCTION f1()")
    assert statements[0].endswith("END;")
    assert statements[1] == "SELECT 2;"


def test_issue194_splitting_function_with_if_block():
    """A CREATE FUNCTION containing an IF ... END IF control structure
    inside its BEGIN...END body must still be split correctly from the
    statement that follows it. None of the semicolons inside the IF block
    (nor the one after END IF) should terminate the function early; only
    the final END; closing the outer BEGIN block should do so.
    """
    sql = (
        "CREATE FUNCTION f2(x INT) RETURNS INT\n"
        "BEGIN\n"
        "  IF x > 0 THEN\n"
        "    RETURN 1;\n"
        "  END IF;\n"
        "  RETURN 0;\n"
        "END;\n"
        "SELECT 2;"
    )
    statements = sqlparse.split(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE FUNCTION f2")
    assert statements[0].endswith("END;")
    assert statements[1] == "SELECT 2;"


def test_split_casewhen_procedure():
    """A CREATE PROCEDURE containing a CASE ... END CASE control structure
    inside its BEGIN...END body must be parsed as a single statement,
    separate from whatever statement follows it. The semicolons that
    terminate the individual WHEN branches, as well as the one after
    END CASE, must not split the procedure definition early.
    """
    sql = (
        "CREATE PROCEDURE p1()\n"
        "BEGIN\n"
        "  CASE\n"
        "    WHEN 1 THEN SELECT 1;\n"
        "    WHEN 2 THEN SELECT 2;\n"
        "  END CASE;\n"
        "END;\n"
        "SELECT 3;"
    )
    statements = sqlparse.split(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE PROCEDURE p1()")
    assert statements[0].endswith("END;")
    assert statements[1] == "SELECT 3;"
