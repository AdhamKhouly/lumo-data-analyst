"""Talk to Lumo in the terminal.

    python -m src.chat                                  # interactive
    python -m src.chat --ask "How did revenue change from week 3 to week 8?"
    python -m src.chat --tool compare_metric '{"metric": "revenue", "start_week": 3, "end_week": 8}'

The --tool form calls one analytics function directly, without Claude. It is handy for
checking what a tool returns and needs no API key.
"""
from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from .agent import Conversation, Lumo, run_tool
from .database import DEFAULT_DB_PATH, Database


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chat with Lumo about the weekly reports.")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--ask", metavar="QUESTION", help="ask one question and exit")
    ap.add_argument("--tool", nargs=2, metavar=("NAME", "JSON_ARGS"), help="call one tool directly (no Claude)")
    ap.add_argument("--show-tools", action="store_true", help="print which tools were called for each answer")
    args = ap.parse_args(argv)
    load_dotenv()

    try:
        db = Database(args.db, read_only=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not open {args.db}: {exc}\nRun `python -m src.ingest` first.", file=sys.stderr)
        return 2

    if args.tool:
        name, raw = args.tool
        print(json.dumps(run_tool(db, name, json.loads(raw or "{}")), indent=2, default=str))
        return 0

    lumo = Lumo(db)
    conversation = Conversation()

    def answer(question: str) -> None:
        result = lumo.ask(question, conversation)
        print(f"\nLumo: {result.text}\n")
        if args.show_tools and result.tool_calls:
            print("  tools: " + ", ".join(f"{c.name}({json.dumps(c.arguments)})" for c in result.tool_calls))

    if args.ask:
        answer(args.ask)
        return 0

    weeks = db.weeks()
    print(f"Lumo is ready ({len(weeks)} weeks loaded). Ask a question, or type /clear or /quit.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("/quit", "/exit", "/q"):
            break
        if question.lower() == "/clear":
            conversation.clear()
            print("Conversation cleared.")
            continue
        answer(question)
    return 0


if __name__ == "__main__":
    sys.exit(main())
