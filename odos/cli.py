"""Command line: ``odos <command>``.

    odos init-db                       create tables
    odos audit [--source mock] [--lookback-days 1] [--suggest]
    odos suggestions [--status PENDING]
    odos approve ID --reviewer NAME [--note TEXT]
    odos reject ID --reviewer NAME [--note TEXT]
    odos eval [--cases eval/cases.jsonl]
    odos api [--port 8000]
    odos ui  [--port 8501]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_init_db(args) -> int:
    from odos.backend.db import get_engine, init_db

    engine = init_db()
    print(f"Odos tables ready ({engine.dialect.name}: {get_engine().url.render_as_string(hide_password=True)})")
    return 0


def cmd_audit(args) -> int:
    from odos.backend.db import init_db, session_scope
    from odos.backend.remediation import generate_suggestions
    from odos.backend.service import EnterpriseAuditor
    from odos.sources import build_source

    init_db()
    source = build_source(args.source)
    with session_scope() as db:
        report = EnterpriseAuditor(db, source).run_audit_cycle(lookback=args.lookback_days)
        if args.suggest:
            from odos.backend.cost_engine import suggestion_to_dict
            from odos.backend.surgeon import Surgeon

            surgeon = Surgeon()
            if not surgeon.available:
                print("No AI provider configured (set OPENAI_API_KEY or GEMINI_API_KEY); skipping suggestions.",
                      file=sys.stderr)
            report["suggestions"] = [suggestion_to_dict(s) for s in generate_suggestions(db, surgeon)]
    _print({"source": source.name, **report})
    return 0


def cmd_suggestions(args) -> int:
    from sqlalchemy import select

    from odos.backend.cost_engine import suggestion_to_dict
    from odos.backend.db import init_db, session_scope
    from odos.backend.models import Suggestion

    init_db()
    with session_scope() as db:
        stmt = select(Suggestion).order_by(Suggestion.created_at.desc()).limit(args.limit)
        if args.status:
            stmt = stmt.where(Suggestion.status == args.status.upper())
        _print([suggestion_to_dict(s) for s in db.scalars(stmt).all()])
    return 0


def cmd_review(args) -> int:
    from odos.backend.cost_engine import suggestion_to_dict
    from odos.backend.db import session_scope
    from odos.backend.remediation import ReviewError, approve, reject

    action = approve if args.command == "approve" else reject
    try:
        with session_scope() as db:
            _print(suggestion_to_dict(action(db, args.id, args.reviewer, args.note)))
    except ReviewError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_eval(args) -> int:
    from odos.backend.surgeon import Surgeon
    from odos.evaluation import load_cases, run_eval

    surgeon = Surgeon()
    if not surgeon.available:
        print("Set OPENAI_API_KEY or GEMINI_API_KEY to run the evaluation.", file=sys.stderr)
        return 1
    report = run_eval(surgeon, load_cases(args.cases) if args.cases else None)
    _print(report)
    return 0 if report["pass_rate"] >= args.min_pass_rate else 2


def cmd_api(args) -> int:
    import uvicorn

    uvicorn.run("odos.backend.api:app", host=args.host, port=args.port)
    return 0


def cmd_ui(args) -> int:
    ui = Path(__file__).resolve().parent / "backend" / "ui.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ui),
                            "--server.port", str(args.port), "--server.address", args.host])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odos", description="Odos Auditor")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the Odos tables").set_defaults(func=cmd_init_db)

    p = sub.add_parser("audit", help="run one audit cycle")
    p.add_argument("--source", choices=["snowflake", "bigquery", "mock"])
    p.add_argument("--lookback-days", type=int, default=1)
    p.add_argument("--suggest", action="store_true", help="ask the AI for rewrites of new anomalies")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("suggestions", help="list AI suggestions")
    p.add_argument("--status", choices=["PENDING", "INVALID", "FAILED", "APPROVED", "REJECTED"])
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_suggestions)

    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} a pending suggestion")
        p.add_argument("id", type=int)
        p.add_argument("--reviewer", required=True)
        p.add_argument("--note")
        p.set_defaults(func=cmd_review)

    p = sub.add_parser("eval", help="score the AI on known-expensive query patterns")
    p.add_argument("--cases")
    p.add_argument("--min-pass-rate", type=float, default=0.0)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("api", help="start the HTTP API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("ui", help="start the Streamlit dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8501)
    p.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
