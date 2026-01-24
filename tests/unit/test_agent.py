from unittest import result

from odos.agent.instrument import SQLAnalyzer


def test_sql_parsing_safety():
    """Ensure the analyzer respects the size limit."""
    huge_query = "SELECT * " + ("WHERE 1=1 " * 5000)

    result = SQLAnalyzer.safe_analyze(huge_query)

    # If safe_analyze returns None on failure/skip, this handles it
    if result is None:
        assert True
    else:
        # Check for standard error keys in your dictionary
        assert any(k in result for k in [
                   "error", "skipped", "warning"]) or result == {}


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
