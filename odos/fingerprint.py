"""Stable SQL fingerprints.

A fingerprint identifies the *shape* of a query, so every run of the same
pipeline query maps to one baseline even when its literal values change
(``WHERE id = 1`` and ``WHERE id = 2`` share a fingerprint).

Fingerprints use SHA-256, so they are identical across processes and machines.
(Python's built-in ``hash()`` is randomised per process and must not be used.)

sqlglot is used when installed; otherwise a regex normaliser is used. Queries
larger than :data:`MAX_PARSE_BYTES` skip AST parsing to keep overhead low.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

try:  # optional dependency
    import sqlglot
    from sqlglot import exp

    SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when sqlglot is absent
    sqlglot = None
    exp = None
    SQLGLOT_AVAILABLE = False

MAX_PARSE_BYTES = 50_000
DEFAULT_DIALECT = "snowflake"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING = re.compile(r"'(?:[^'\\]|\\.|'')*'")
_NUMBER = re.compile(r"(?<![\w.$])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
_PLACEHOLDER_LIST = re.compile(r"\(\s*\?(?:\s*,\s*\?)+\s*\)")
_WHITESPACE = re.compile(r"\s+")
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([A-Za-z_\"][\w.$\"]*)", re.I)


def _regex_normalize(sql: str) -> str:
    text = _BLOCK_COMMENT.sub(" ", sql)
    text = _LINE_COMMENT.sub(" ", text)
    text = _STRING.sub("?", text)
    text = _NUMBER.sub("?", text)
    text = _PLACEHOLDER_LIST.sub("(?)", text)
    text = _WHITESPACE.sub(" ", text).strip().rstrip(";").strip()
    return text.lower()


def _ast_normalize(sql: str, dialect: str) -> str:
    tree = sqlglot.parse_one(sql, read=dialect)
    tree = tree.transform(lambda node: exp.Placeholder() if isinstance(node, exp.Literal) else node)
    text = tree.sql(dialect=dialect, comments=False)
    text = _PLACEHOLDER_LIST.sub("(?)", text)
    return _WHITESPACE.sub(" ", text).strip().lower()


def normalize_sql(sql: str, dialect: str = DEFAULT_DIALECT) -> str:
    """Return canonical SQL with comments removed and literals replaced by ``?``."""
    if not sql:
        return ""
    if SQLGLOT_AVAILABLE and len(sql.encode("utf-8", "ignore")) <= MAX_PARSE_BYTES:
        try:
            return _ast_normalize(sql, dialect)
        except Exception:
            pass  # unparseable SQL falls back to the regex normaliser
    return _regex_normalize(sql)


def fingerprint(sql: str, dialect: str = DEFAULT_DIALECT) -> str:
    """16-hex-character SHA-256 fingerprint of the normalised query."""
    return hashlib.sha256(normalize_sql(sql, dialect).encode("utf-8")).hexdigest()[:16]


def tables_in(sql: str, dialect: str = DEFAULT_DIALECT) -> set[str]:
    """Lower-cased table names referenced by a query (CTE names excluded)."""
    if not sql:
        return set()
    if SQLGLOT_AVAILABLE and len(sql.encode("utf-8", "ignore")) <= MAX_PARSE_BYTES:
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
            ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
            names = set()
            for table in tree.find_all(exp.Table):
                parts = [p for p in (table.catalog, table.db, table.name) if p]
                name = ".".join(parts).lower()
                if table.name.lower() not in ctes:
                    names.add(name)
            return names
        except Exception:
            pass
    text = _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql))
    ctes = {m.lower() for m in re.findall(r"\b(\w+)\s+as\s*\(", text, re.I)}
    found = {m.replace('"', "").lower() for m in _TABLE_REF.findall(text)}
    return {t for t in found if t.split(".")[-1] not in ctes and t != "("}


def analyze(sql: str, dialect: str = DEFAULT_DIALECT) -> dict[str, Any]:
    """Fingerprint, referenced tables and a rough complexity score."""
    if not sql:
        return {}
    complexity = None
    if SQLGLOT_AVAILABLE and len(sql.encode("utf-8", "ignore")) <= MAX_PARSE_BYTES:
        try:
            complexity = sum(1 for _ in sqlglot.parse_one(sql, read=dialect).walk())
        except Exception:
            complexity = None
    return {
        "fingerprint": fingerprint(sql, dialect),
        "tables": sorted(tables_in(sql, dialect)),
        "complexity": complexity,
    }
