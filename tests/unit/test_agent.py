from pulseflow.agent.instrument import SQLAnalyzer


def test_sql_parsing_safety():
    """
    Ensure the analyzer respects the size limit.
    """
    # 1. Create a massive fake query (> 50KB)
    huge_query = "SELECT * FROM users " + ("WHERE 1=1 " * 10000)

    # 2. Run Safe Analyze
    result = SQLAnalyzer.safe_analyze(huge_query)

    # 3. Assert it skipped execution explicitly
    assert result["status"] == "skipped"
    assert "reason" in result


def test_sql_fingerprinting():
    """
    Ensure two identical queries (ignoring formatting) get the same fingerprint.
    """
    q1 = "SELECT * FROM table"
    q2 = "select * from table -- comment"

    res1 = SQLAnalyzer.safe_analyze(q1)
    res2 = SQLAnalyzer.safe_analyze(q2)

    # Hashes should match because logic is identical
    assert res1['fingerprint'] == res2['fingerprint']
