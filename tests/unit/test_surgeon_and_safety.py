import json

import pytest

from odos.backend import sql_safety
from odos.backend.sql_safety import redact_sql, redact_text, validate_suggestion
from odos.backend.surgeon import ResponseError, Surgeon, _parse_json

GOOD = {"diagnosis": "Scans all columns.", "suggested_sql": "SELECT id, amount FROM sales.orders WHERE day = ?",
        "strategy": "Column pruning", "estimated_savings_pct": "40%"}
ORIGINAL = "SELECT * FROM sales.orders WHERE day = '2026-01-01' AND customer_email = 'x@y.com'"


@pytest.fixture(params=["sqlglot", "regex"])
def parser_mode(request, monkeypatch):
    if request.param == "sqlglot":
        pytest.importorskip("sqlglot")
    else:
        monkeypatch.setattr(sql_safety, "SQLGLOT_AVAILABLE", False)
        import odos.fingerprint as fp
        monkeypatch.setattr(fp, "SQLGLOT_AVAILABLE", False)
    return request.param


def test_redact_sql_removes_literals(parser_mode):
    out = redact_sql(ORIGINAL)
    assert "x@y.com" not in out and "2026" not in out
    assert "?" in out


def test_redact_text_masks_secrets_and_truncates():
    text = "password=hunter2 token: abc123 postgresql://u:pw@host/db sk-abcdefghijklmnop " + "x" * 5000
    out = redact_text(text, max_chars=200)
    for secret in ("hunter2", "abc123", ":pw@", "sk-abcdefghijklmnop"):
        assert secret not in out
    assert len(out) < 260


def test_validation(parser_mode):
    ok, _ = validate_suggestion(ORIGINAL, "SELECT id FROM sales.orders WHERE day = ?")
    assert ok
    ok, notes = validate_suggestion(ORIGINAL, "DELETE FROM sales.orders")
    assert not ok and any("writes" in n for n in notes)
    ok, notes = validate_suggestion(ORIGINAL, "SELECT * FROM sales.orders JOIN hr.salaries s ON 1 = 1")
    assert not ok and any("hr.salaries" in n for n in notes)
    ok, notes = validate_suggestion(ORIGINAL, "SELECT 1 FROM sales.orders; DROP TABLE x")
    assert not ok
    assert validate_suggestion(ORIGINAL, "  ")[0] is False


def test_parse_json_handles_fences_and_rejects_junk():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ResponseError):
        _parse_json("no json here")


def test_falls_back_to_second_provider(fake_provider_cls):
    first = fake_provider_cls("openai", [RuntimeError("overloaded")])
    second = fake_provider_cls("gemini", [GOOD])
    result = Surgeon(providers=[first, second]).optimize_sql(ORIGINAL, "t1", cost_usd=12, baseline_usd=2)
    assert result.status == "VALID"
    assert result.provider == "gemini"
    assert result.estimated_savings_pct == 40
    assert "x@y.com" not in second.prompts[0]           # literals never sent
    assert "x@y.com" not in result.sent_sql


def test_malformed_response_moves_to_next_provider(fake_provider_cls):
    bad = fake_provider_cls("openai", [{"diagnosis": "only this"}])
    good = fake_provider_cls("gemini", [GOOD])
    assert Surgeon(providers=[bad, good]).optimize_sql(ORIGINAL).provider == "gemini"


def test_all_providers_fail_returns_failed_without_fake_suggestion(fake_provider_cls):
    result = Surgeon(providers=[fake_provider_cls("openai", [RuntimeError("down")])]).optimize_sql(ORIGINAL)
    assert result.status == "FAILED"
    assert result.suggested_sql is None


def test_unsafe_suggestion_is_marked_invalid(fake_provider_cls):
    bad_sql = {**GOOD, "suggested_sql": "SELECT * FROM sales.orders JOIN hr.salaries ON 1 = 1"}
    result = Surgeon(providers=[fake_provider_cls("openai", [bad_sql])]).optimize_sql(ORIGINAL)
    assert result.status == "INVALID"
    assert result.notes


def test_no_provider_means_failed():
    assert Surgeon(providers=[]).optimize_sql("SELECT 1").status == "FAILED"


def test_diagnosis_uses_ai_then_rules(fake_provider_cls):
    ai = fake_provider_cls("openai", [{"root_cause": "Expired key", "confidence": "High", "fix_action": "Rotate"}])
    out = Surgeon(providers=[ai]).diagnose_pipeline_failure("auth failed password=secret1", "trace")
    assert out["source"] == "openai" and out["root_cause"] == "Expired key"
    assert "secret1" not in ai.prompts[0]
    rules = Surgeon(providers=[]).diagnose_pipeline_failure("SQL compilation error: invalid identifier 'X'")
    assert rules["source"] == "rules" and "schema" in rules["root_cause"].lower()


def test_log_for_finetuning_writes_jsonl(tmp_path):
    Surgeon(providers=[]).log_for_finetuning("SELECT 1", "SELECT 2", True, "t")
    line = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[0])
    assert line["label"] == 1
