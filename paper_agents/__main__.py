from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, time, timezone
from pathlib import Path

from .agents import WorkflowAgent, papers_to_jsonable
from .config import load_config
from .db import PaperStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily VLA/CV paper agent workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config", help="Create config.json from config.example.json")
    init_parser.add_argument("--target", default="config.json")

    run_parser = subparsers.add_parser("run", help="Run the daily paper workflow")
    run_parser.add_argument("--config", default="config.json")
    run_parser.add_argument("--date", help="Run date in YYYY-MM-DD. Defaults to today in UTC.")
    run_parser.add_argument("--days", type=int, help="Lookback window in days.")
    run_parser.add_argument("--no-llm", action="store_true", help="Disable OpenAI summarization/classification.")
    run_parser.add_argument("--skip-semantic", action="store_true", help="Skip Semantic Scholar enrichment.")
    run_parser.add_argument("--json-out", help="Optional path for full JSON output.")
    run_parser.add_argument("--notify-feishu", action="store_true", help="Send selected papers to Feishu webhook.")

    args = parser.parse_args()
    if args.command == "init-config":
        init_config(args.target)
    elif args.command == "run":
        run(args)


def init_config(target: str) -> None:
    source = Path(__file__).resolve().parent.parent / "config.example.json"
    destination = Path(target)
    if destination.exists():
        raise SystemExit(f"{destination} already exists")
    shutil.copyfile(source, destination)
    print(f"Created {destination}")


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config if Path(args.config).exists() else None)
    if args.no_llm:
        config.llm.enabled = False
    if args.skip_semantic:
        config.semantic_scholar.enabled = False

    run_date = _parse_run_date(args.date)
    workflow = WorkflowAgent(config)
    all_papers, selected, report = workflow.run(run_date=run_date, days=args.days, notify_feishu=args.notify_feishu)

    store = PaperStore(config.database.path)
    try:
        store.upsert_many(all_papers)
    finally:
        store.close()

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(papers_to_jsonable(all_papers), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Collected: {len(all_papers)}")
    print(f"Selected: {len(selected)}")
    print(f"Report: {report}")
    print(f"Database: {config.database.path}")


def _parse_run_date(value: str | None) -> datetime:
    if value:
        date_value = datetime.strptime(value, "%Y-%m-%d").date()
        return datetime.combine(date_value, time.max, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


if __name__ == "__main__":
    main()
