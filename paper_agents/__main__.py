from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .agents import CuratorAgent, NotifierAgent, WorkflowAgent, papers_to_jsonable
from .config import load_config
from .db import PaperStore
from .models import Paper


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily VLA/CV paper agent workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config", help="Create config.json from config.example.json")
    init_parser.add_argument("--target", default="config.json")

    run_parser = subparsers.add_parser("run", help="Run the daily paper workflow")
    run_parser.add_argument("--config", default="config.json")
    run_parser.add_argument("--date", help="Run date in YYYY-MM-DD. Defaults to today in UTC.")
    run_parser.add_argument("--days", type=int, help="Lookback window in days.")
    run_parser.add_argument(
        "--since-last-sunday",
        action="store_true",
        help="Collect from the most recent Sunday 00:00 to the run date, using --timezone.",
    )
    run_parser.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for --date and --since-last-sunday.")
    run_parser.add_argument("--no-llm", action="store_true", help="Disable OpenAI summarization/classification.")
    run_parser.add_argument("--skip-semantic", action="store_true", help="Skip Semantic Scholar enrichment.")
    run_parser.add_argument("--json-out", help="Optional path for full JSON output.")
    run_parser.add_argument("--notify-feishu", action="store_true", help="Send selected papers to Feishu webhook.")

    feishu_parser = subparsers.add_parser("test-feishu", help="Send a small Feishu test notification.")
    feishu_parser.add_argument("--config", default="config.json")
    feishu_parser.add_argument("--message", default="论文日报测试：飞书机器人推送已连通。")

    notify_parser = subparsers.add_parser("notify-feishu", help="Send selected papers from a JSON file to Feishu.")
    notify_parser.add_argument("--config", default="config.json")
    notify_parser.add_argument("--json", default="latest_papers.json", help="JSON file produced by run --json-out.")
    notify_parser.add_argument("--date", help="Report date in YYYY-MM-DD. Defaults to today.")
    notify_parser.add_argument("--timezone", default="Asia/Shanghai")
    notify_parser.add_argument("--report", help="Optional report path to mention in the Feishu message.")

    args = parser.parse_args()
    if args.command == "init-config":
        init_config(args.target)
    elif args.command == "run":
        run(args)
    elif args.command == "test-feishu":
        test_feishu(args)
    elif args.command == "notify-feishu":
        notify_feishu(args)


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

    run_date = _parse_run_date(args.date, args.timezone)
    start_date = _last_sunday_start(run_date, args.timezone) if args.since_last_sunday else None
    workflow = WorkflowAgent(config)
    all_papers, selected, report = workflow.run(
        run_date=run_date,
        days=args.days,
        start_date=start_date,
        notify_feishu=args.notify_feishu,
    )

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


def test_feishu(args: argparse.Namespace) -> None:
    config = load_config(args.config if Path(args.config).exists() else None)
    notifier = NotifierAgent(config)
    if not notifier.available():
        raise SystemExit("FEISHU_WEBHOOK_URL is not configured.")
    notifier.client.send_text(args.message)
    print("Feishu test notification sent.")


def notify_feishu(args: argparse.Namespace) -> None:
    config = load_config(args.config if Path(args.config).exists() else None)
    json_path = Path(args.json)
    if not json_path.exists():
        raise SystemExit(f"{json_path} does not exist. Run with --json-out first.")
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    papers = [Paper(**item) for item in payload]
    selected = CuratorAgent(config).run(papers)
    notifier = NotifierAgent(config)
    if not notifier.available():
        raise SystemExit("FEISHU_WEBHOOK_URL is not configured.")
    report = Path(args.report) if args.report else None
    notifier.run(selected, run_date=_parse_run_date(args.date, args.timezone), report=report)


def _parse_run_date(value: str | None, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if value:
        date_value = datetime.strptime(value, "%Y-%m-%d").date()
        return datetime.combine(date_value, time.max, tzinfo=tz)
    return datetime.now(tz)


def _last_sunday_start(run_date: datetime, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    local_date = run_date.astimezone(tz).date()
    days_since_sunday = (local_date.weekday() + 1) % 7
    sunday = local_date - timedelta(days=days_since_sunday)
    return datetime.combine(sunday, time.min, tzinfo=tz)


if __name__ == "__main__":
    main()
