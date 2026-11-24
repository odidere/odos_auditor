"""AI assistance: SQL cost rewrites and pipeline failure diagnosis.

Safety model:

* Literals are redacted and secrets masked before anything is sent.
* Every provider call has a timeout and an output-token limit.
* Responses must be JSON with the expected fields; anything else is discarded.
* Rewrites are validated (single read-only statement, same tables) and stored
  as suggestions for a person to approve or reject. Odos never runs them.
* If no provider answers, diagnosis falls back to simple rules; rewrites are
  reported as FAILED (the original SQL is never passed off as a suggestion).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol

from odos.backend.sql_safety import redact_sql, redact_text, validate_suggestion
from odos.config import section

logger = logging.getLogger("odos.surgeon")

SQL_SYSTEM_PROMPT = (
    "You are a senior data engineer who reduces warehouse cost without changing query results. "
    "Reply with a single JSON object only."
)
SQL_PROMPT = """Suggest a cheaper version of this {dialect} query that returns the same results.

Rules:
- Keep every '?' placeholder; each stands for a redacted literal value.
- Do not read any table the query does not already read.
- Return one read-only statement.
- If there is no safe improvement, return the query unchanged and set "strategy" to "none".

Context: this query's latest run cost ${cost:.2f} against a usual ${baseline:.2f}.

Query:
```sql
{sql}
```

Reply as JSON with exactly these keys:
{{"diagnosis": "why it is expensive (1-2 sentences)",
  "suggested_sql": "the rewritten query",
  "strategy": "short name of the technique",
  "estimated_savings_pct": 0}}"""

PIPELINE_SYSTEM_PROMPT = "You are a site reliability engineer for data pipelines. Reply with JSON only."
PIPELINE_PROMPT = """Find the most likely root cause of this pipeline failure.

Error:
{error}

Stack trace (may be truncated):
{trace}

Reply as JSON with exactly these keys:
{{"root_cause": "max 15 words", "confidence": "High|Medium|Low", "fix_action": "concrete steps"}}"""

SQL_KEYS = {"diagnosis": str, "suggested_sql": str, "strategy": str}
PIPELINE_KEYS = {"root_cause": str, "confidence": str, "fix_action": str}


class ResponseError(ValueError):
    """The model answered, but not in the required shape."""


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]: ...


def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        raise ResponseError("empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{"):]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ResponseError("no JSON object in response")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ResponseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResponseError("JSON is not an object")
    return data


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float, max_tokens: int):
        import openai

        self.model = model
        self.max_tokens = max_tokens
        self.client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_completion_tokens=self.max_tokens,
        )
        return _parse_json(response.choices[0].message.content)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float, max_tokens: int):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
        self.max_tokens = max_tokens
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=self.max_tokens,
            ),
        )
        return _parse_json(response.text)


def providers_from_env(settings: dict[str, Any] | None = None) -> list[Provider]:
    """OpenAI first, then Gemini, for whichever API keys are set."""
    s = settings or section("ai")
    timeout = float(s.get("timeout_sec", 30))
    max_tokens = int(s.get("max_output_tokens", 1500))
    providers: list[Provider] = []
    if os.getenv("OPENAI_API_KEY"):
        try:
            providers.append(OpenAIProvider(os.environ["OPENAI_API_KEY"],
                                            os.getenv("ODOS_OPENAI_MODEL", s.get("openai_model", "gpt-4.1-mini")),
                                            timeout, max_tokens))
        except ImportError:
            logger.warning("OPENAI_API_KEY is set but the openai package is not installed")
    if os.getenv("GEMINI_API_KEY"):
        try:
            providers.append(GeminiProvider(os.environ["GEMINI_API_KEY"],
                                            os.getenv("ODOS_GEMINI_MODEL", s.get("gemini_model", "gemini-2.5-flash")),
                                            timeout, max_tokens))
        except ImportError:
            logger.warning("GEMINI_API_KEY is set but the google-genai package is not installed")
    return providers


@dataclass
class SqlSuggestionResult:
    status: str                      # VALID, INVALID or FAILED
    sent_sql: str                    # exactly what the model saw
    diagnosis: str | None = None
    suggested_sql: str | None = None
    strategy: str | None = None
    estimated_savings_pct: int = 0
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_pct(value: Any) -> int:
    try:
        return max(0, min(100, int(round(float(str(value).strip().rstrip("%"))))))
    except (TypeError, ValueError):
        return 0


def _check_keys(data: dict[str, Any], keys: dict[str, type]) -> dict[str, Any]:
    missing = [k for k in keys if not isinstance(data.get(k), keys[k]) or not str(data.get(k)).strip()]
    if missing:
        raise ResponseError("missing or empty fields: " + ", ".join(missing))
    return data


class Surgeon:
    def __init__(self, providers: list[Provider] | None = None, settings: dict[str, Any] | None = None):
        self.settings = settings or section("ai")
        self.providers = providers if providers is not None else providers_from_env(self.settings)
        self.dialect = self.settings.get("dialect", "snowflake")
        self.send_literals = bool(self.settings.get("send_literals", False))

    @property
    def available(self) -> bool:
        return bool(self.providers) and bool(self.settings.get("enabled", True))

    def _ask(self, system: str, prompt: str, keys: dict[str, type]) -> tuple[dict[str, Any], Provider, int]:
        errors = []
        for provider in self.providers:
            t0 = time.perf_counter()
            try:
                data = _check_keys(provider.complete_json(system, prompt), keys)
                return data, provider, int((time.perf_counter() - t0) * 1000)
            except Exception as exc:
                logger.warning("Odos surgeon: %s failed (%s)", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
        raise RuntimeError("; ".join(errors) or "no AI provider configured")

    # --- SQL rewrites -------------------------------------------------------
    def optimize_sql(self, query_text: str, task_id: str = "adhoc", cost_usd: float = 0.0,
                     baseline_usd: float = 0.0, already_redacted: bool = False) -> SqlSuggestionResult:
        sent = query_text if (already_redacted or self.send_literals) else redact_sql(query_text, self.dialect)
        if not self.available:
            return SqlSuggestionResult(status="FAILED", sent_sql=sent, notes=["AI is disabled or no provider is configured."])
        prompt = SQL_PROMPT.format(dialect=self.dialect, sql=sent, cost=cost_usd, baseline=baseline_usd)
        try:
            data, provider, latency = self._ask(SQL_SYSTEM_PROMPT, prompt, SQL_KEYS)
        except RuntimeError as exc:
            return SqlSuggestionResult(status="FAILED", sent_sql=sent, notes=[str(exc)])
        result = SqlSuggestionResult(
            status="VALID", sent_sql=sent, diagnosis=data["diagnosis"].strip(),
            suggested_sql=data["suggested_sql"].strip(), strategy=data["strategy"].strip(),
            estimated_savings_pct=_coerce_pct(data.get("estimated_savings_pct")),
            provider=provider.name, model=provider.model, latency_ms=latency,
        )
        ok, notes = validate_suggestion(sent, result.suggested_sql, self.dialect)
        if not ok:
            result.status, result.notes = "INVALID", notes
        logger.info("Odos surgeon: %s -> %s via %s", task_id, result.status, provider.name)
        return result

    # --- Failure diagnosis --------------------------------------------------
    def diagnose_pipeline_failure(self, error_message: str, stack_trace: str = "") -> dict[str, Any]:
        if self.available:
            prompt = PIPELINE_PROMPT.format(error=redact_text(error_message, 1000), trace=redact_text(stack_trace))
            try:
                data, provider, latency = self._ask(PIPELINE_SYSTEM_PROMPT, prompt, PIPELINE_KEYS)
                return {**{k: data[k] for k in PIPELINE_KEYS}, "source": provider.name, "latency_ms": latency}
            except RuntimeError as exc:
                logger.warning("Odos surgeon: AI diagnosis unavailable (%s); using rules", exc)
        return {**self._heuristic_diagnosis(str(error_message or "").lower()), "source": "rules"}

    @staticmethod
    def _heuristic_diagnosis(err: str) -> dict[str, str]:
        rules = [
            (("timeout", "timed out", "connection"), "Network or connection timeout", "High",
             "Check the target is reachable (network policy, firewall, credentials expiry) and add retries "
             "with exponential backoff."),
            (("oomkilled", "memoryerror", "out of memory"), "Resource exhaustion (memory)", "High",
             "Process data in chunks or stream it, or give the task more memory."),
            (("deadlock",), "Database concurrency conflict", "High",
             "Access rows in a consistent order and keep transactions short."),
            (("invalid identifier", "column", "schema"), "Upstream schema change", "Medium",
             "Compare the source schema with what the pipeline expects; add a schema contract check."),
            (("permission", "not authorized", "access denied", "insufficient privileges"),
             "Missing privileges", "High", "Grant the pipeline's role the privilege named in the error."),
        ]
        for needles, cause, confidence, fix in rules:
            if any(n in err for n in needles):
                return {"root_cause": cause, "confidence": confidence, "fix_action": fix}
        return {"root_cause": "Unclassified application error", "confidence": "Low",
                "fix_action": "Read the stack trace from the bottom up; the first frame in your code is usually the cause."}

    # --- Compatibility ------------------------------------------------------
    def log_for_finetuning(self, original_sql: str, suggested_sql: str, accepted: bool, task_id: str) -> None:
        """Append a reviewed example to the decisions dataset (JSON Lines)."""
        path = os.getenv("ODOS_DECISIONS_PATH") or os.getenv("PULSEFLOW_DATASET_PATH") or "odos_decisions.jsonl"
        entry = {"timestamp": datetime.now().isoformat(), "task_id": task_id, "input_sql": original_sql,
                 "output_sql": suggested_sql, "label": 1 if accepted else 0}
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
