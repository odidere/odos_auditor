import os
import subprocess
import sys

import pytest

from odos import fingerprint as fpmod
from odos.fingerprint import _regex_normalize, fingerprint, normalize_sql, tables_in


def test_regex_normaliser_replaces_literals_and_comments():
    sql = "SELECT * FROM orders -- note\nWHERE id = 42 AND email = 'a@b.com' /* x */ AND d IN (1, 2, 3);"
    assert _regex_normalize(sql) == "select * from orders where id = ? and email = ? and d in (?)"


def test_regex_normaliser_keeps_identifiers_with_digits():
    assert _regex_normalize("SELECT col_2 FROM t1 WHERE x = 3") == "select col_2 from t1 where x = ?"


def test_same_shape_different_literals_share_fingerprint():
    a = fingerprint("SELECT * FROM orders WHERE id = 1 AND day = '2026-01-01'")
    b = fingerprint("select *  from orders\n where id = 99 and day = '2026-02-02' -- rerun")
    c = fingerprint("SELECT * FROM orders WHERE customer_id = 1")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_fingerprint_is_stable_across_processes():
    code = "from odos.fingerprint import fingerprint; print(fingerprint('SELECT a FROM t WHERE b = 1'))"
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outputs = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": root}
        outputs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                                   text=True, check=True).stdout.strip())
    assert len(outputs) == 1


def test_tables_in_excludes_ctes():
    sql = "WITH recent AS (SELECT * FROM raw.orders) SELECT * FROM recent JOIN crm.customers c ON 1 = 1"
    assert tables_in(sql) == {"raw.orders", "crm.customers"}


def test_regex_fallback_when_sqlglot_missing(monkeypatch):
    monkeypatch.setattr(fpmod, "SQLGLOT_AVAILABLE", False)
    assert normalize_sql("SELECT 1 FROM t WHERE x = 'y'") == "select ? from t where x = ?"
    assert fpmod.tables_in("SELECT * FROM a.b JOIN c ON a.id = c.id") == {"a.b", "c"}


def test_sqlglot_path_normalises_literals():
    pytest.importorskip("sqlglot")
    assert "?" in normalize_sql("SELECT * FROM t WHERE id = 5")
    assert fingerprint("SELECT * FROM t WHERE id IN (1,2)") == fingerprint("SELECT * FROM t WHERE id IN (7, 8, 9)")
