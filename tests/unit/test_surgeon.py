import json
from unittest.mock import MagicMock, patch

import pytest

from odos.backend.surgeon import Surgeon


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")


def test_surgeon_optimization_logic(mock_env):
    """Verifies that optimize_sql triggers the AI fallback correctly."""
    with patch("openai.resources.chat.Completions.create") as mock_oa, \
            patch("google.genai.Client") as mock_gem:

        # 1. Simulate OpenAI Failure
        mock_oa.side_effect = Exception("OpenAI Overloaded")

        # 2. Setup Gemini Success Mock
        # Mocking the .text attribute returned by the new Google GenAI SDK
        mock_gem.return_value.models.generate_content.return_value.text = json.dumps({
            "diagnosis": "Gemini Optimization",
            "suggested_sql": "SELECT 1",
            "estimated_savings_pct": 45
        })

        surgeon = Surgeon()

        # 3. ACT: Using the actual method found in your dir() dump
        result = surgeon.optimize_sql(
            "SELECT * FROM large_table", "query_hash_123")

        # 4. ASSERT
        assert result["estimated_savings_pct"] == 45
        assert result["diagnosis"] == "Gemini Optimization"


def test_surgeon_pipeline_diagnosis(mock_env):
    """Tests the pipeline-specific diagnosis method found in dir()."""
    with patch("openai.resources.chat.Completions.create") as mock_oa:
        mock_oa.return_value.choices[0].message.content = json.dumps({
            "error_type": "Connection",
            "root_cause": "Timeout",
            "fix": "Check VPN"
        })

        surgeon = Surgeon()
        # Using your actual method name
        result = surgeon.diagnose_pipeline_failure(
            "ConnectionTimeout: 504", "ingest_pipe")

        assert "VPN" in result["fix"]
