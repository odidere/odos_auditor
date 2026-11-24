"""Guardrails around anything sent to, or received from, an LLM.

* :func:`redact_sql` replaces string and number literals with ``?`` so customer
  values (emails, ids, amounts) never leave your environment.
* :func:`redact_text` masks secrets in error messages and stack traces.
* :func:`validate_suggestion` checks an AI rewrite before a person sees it.
"""
from __future__ import annotations

import re

from odos.fingerprint import MAX_PARSE_BYTES, SQLGLOT_AVAILABLE, tables_in

if SQLGLOT_AVAILABLE:
    import sqlglot
    from sqlglot import exp

_STRING = re.compile(r"'(?:[^'\\]|\\.|'')*'")
_NUMBER = re.compile(r"(?<![\w.$?])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|put|remove|call|execute)\b", re.I)
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)(\s*[=:]\s*)([^\s,;'\"]+)"),
     r"\1\2***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[\w.\-]+"), r"\1***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}\b"), "sk-***"),
    (re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"), r"\1***\2"),
]
MAX_TRACE_CHARS = 4000


def redact_sql(sql: str, dialect: str = "snowflake") -> str:
    """Readable SQL with literals replaced by ``?``."""
    if not sql:
        return sql
    if SQLGLOT_AVAILABLE and len(sql.encode("utf-8", "ignore")) <= MAX_PARSE_BYTES:
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
            tree = tree.transform(lambda n: exp.Placeholder() if isinstance(n, exp.Literal) else n)
            return tree.sql(dialect=dialect, pretty=True, comments=False)
        except Exception:
            pass
    text = _STRING.sub("?", sql)
    return _NUMBER.sub("?", text)


def redact_text(text: str | None, max_chars: int = MAX_TRACE_CHARS) -> str:
    """Mask secrets and keep the last ``max_chars`` characters (where errors are)."""
    if not text:
        return ""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > max_chars:
        text = "...[truncated]...\n" + text[-max_chars:]
    return text


def _statement_count(sql: str) -> int:
    stripped = _STRING.sub("''", sql)
    return len([s for s in stripped.split(";") if s.strip()])


def _is_read_only(sql: str, dialect: str) -> bool:
    if SQLGLOT_AVAILABLE:
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
            return isinstance(tree, (exp.Select, exp.Union, exp.Subquery)) or tree.key in {"select", "union", "with"}
        except Exception:
            pass
    head = _STRING.sub("''", sql).lstrip().lower()
    return head.startswith(("select", "with", "(")) and not _WRITE_KEYWORDS.search(_STRING.sub("''", sql))


def validate_suggestion(original_sql: str, suggested_sql: str | None, dialect: str = "snowflake") -> tuple[bool, list[str]]:
    """Return (ok, notes). A suggestion is rejected when it:

    * is empty or contains more than one statement,
    * cannot be parsed (when sqlglot is installed),
    * turns a read-only query into one that writes or changes objects,
    * reads tables the original query did not read.
    """
    notes: list[str] = []
    if not suggested_sql or not suggested_sql.strip():
        return False, ["Empty suggestion."]
    if _statement_count(suggested_sql) > 1:
        notes.append("Suggestion contains more than one statement.")
    if SQLGLOT_AVAILABLE:
        try:
            sqlglot.parse_one(suggested_sql, read=dialect)
        except Exception as exc:
            notes.append(f"Suggestion does not parse as {dialect} SQL: {exc}")
    if _is_read_only(original_sql, dialect) and not _is_read_only(suggested_sql, dialect):
        notes.append("Original query only reads data; the suggestion writes or changes objects.")
    new_tables = tables_in(suggested_sql, dialect) - tables_in(original_sql, dialect)
    if new_tables:
        notes.append("Suggestion reads tables not in the original: " + ", ".join(sorted(new_tables)))
    return not notes, notes
