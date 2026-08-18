"""Command-line interface for the Personal AI Outreach System."""

import argparse
import asyncio
import logging
import sys

from backup import create_database_backup
from config import settings
from db.database import get_or_create_company, get_system_stats, init_db, save_opportunity
from discovery.manager import DiscoveryManager
from heartbeat import run_anti_idle_pulse
from pipeline.orchestrator import PipelineOrchestrator
from profile.parser import load_user_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cli")

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main_async():
    parser = argparse.ArgumentParser(description="Personal AI Job & Startup Outreach CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: status
    subparsers.add_parser("status", help="Display pipeline metrics & DB stats")

    # Command: profile
    subparsers.add_parser("profile", help="Display loaded candidate profile & targeting")

    # Command: init-db
    subparsers.add_parser("init-db", help="Initialize or verify SQLite schema")

    # Command: discover
    discover_parser = subparsers.add_parser("discover", help="Run discovery connectors")
    discover_parser.add_argument("--source", type=str, default=None, help="Connector name (e.g. yc, producthunt, ashby, india, sec_edgar, all)")
    discover_parser.add_argument("--limit", type=int, default=10, help="Max items per source")

    # Command: process
    process_parser = subparsers.add_parser("process", help="Process an opportunity through LangGraph")
    process_parser.add_argument("opportunity_id", type=int, help="Opportunity ID to evaluate and draft")

    # Command: add-watchlist
    watchlist_parser = subparsers.add_parser("add-watchlist", help="Add a company to the watchlist")
    watchlist_parser.add_argument("name", type=str, help="Company name")
    watchlist_parser.add_argument("domain", type=str, help="Company domain, e.g. cursor.com")
    watchlist_parser.add_argument("--stage", type=str, default="seed", help="Funding stage")
    watchlist_parser.add_argument("--description", type=str, default="", help="Company description")

    # Command: heartbeat
    subparsers.add_parser("heartbeat", help="Run Oracle anti-idle heartbeat pulse")

    # Command: backup
    subparsers.add_parser("backup", help="Create a database backup snapshot")

    # Command: start-bot
    subparsers.add_parser("start-bot", help="Run Telegram bot long-polling standalone")

    args = parser.parse_args()

    if not args.command or args.command == "status":
        init_db()
        stats = get_system_stats()
        print("\n" + "=" * 50)
        print(f"📊 PIPELINE STATUS ({'DRY-RUN' if settings.DRY_RUN else 'LIVE'})")
        print("=" * 50)
        for k, v in stats.items():
            print(f"  {k:30}: {v}")
        print("=" * 50 + "\n")

    elif args.command == "init-db":
        init_db()
        print("✅ Database schema initialized at", settings.DATABASE_PATH)

    elif args.command == "profile":
        profile = load_user_profile()
        print("\n" + "=" * 50)
        print(f"👤 CANDIDATE: {profile.candidate.full_name}")
        print(f"Headline: {profile.candidate.headline}")
        print(f"Target Stages: {profile.targeting.target_stages}")
        print(f"Target Domains: {profile.targeting.target_domains}")
        print(f"Min Fit Score: {profile.targeting.min_fit_score}/100")
        print("=" * 50 + "\n")

    elif args.command == "discover":
        init_db()
        mgr = DiscoveryManager()
        sources = [args.source] if args.source and args.source != "all" else None
        print(f"🔍 Running discovery sweep ({sources or 'all sources'})...")
        new_ids = await mgr.run_discovery_sweep(sources=sources, limit_per_source=args.limit)
        print(f"✅ Discovery complete. Ingested {len(new_ids)} new opportunities: {new_ids}")

    elif args.command == "process":
        init_db()
        orchestrator = PipelineOrchestrator()
        print(f"🧠 Processing opportunity #{args.opportunity_id} through LangGraph...")
        result = await orchestrator.process_opportunity(args.opportunity_id)
        if result:
            print("\n" + "=" * 50)
            print(f"🔥 PAUSED AT HUMAN GATE (Score: {result.get('fit_score')}/100)")
            print("=" * 50)
            print(f"Company: {result.get('company_name')}")
            print(f"Recipient: {result.get('contact_name')} ({result.get('contact_email')})")
            print(f"Subject: {result.get('draft_subject')}")
            print(f"\nBody:\n{result.get('draft_body')}")
            print("=" * 50 + "\n")
        else:
            print(f"✅ Opportunity #{args.opportunity_id} processed (or filtered out).")

    elif args.command == "add-watchlist":
        init_db()
        c_id = get_or_create_company(
            domain=args.domain,
            name=args.name,
            website=f"https://{args.domain}",
            stage=args.stage,
            source="watchlist_cli",
            description=args.description,
        )
        opp_id = save_opportunity(
            company_id=c_id,
            type_="founder_reachout",
            title=f"{args.name} — Watchlist Target",
            url=f"https://{args.domain}",
            raw_content=args.description,
        )
        print(f"✅ Added {args.name} to database (Company ID: {c_id}, Opp ID: {opp_id})")

    elif args.command == "heartbeat":
        run_anti_idle_pulse(duration_seconds=10)
        print("✅ Anti-idle pulse finished.")

    elif args.command == "backup":
        bk = create_database_backup()
        print(f"✅ Backup created at {bk}")

    elif args.command == "start-bot":
        from bot.telegram_bot import TelegramBotController
        print("🤖 Starting Telegram Bot long-polling...")
        bot = TelegramBotController()
        app = bot.build_application()
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        print("🟢 Bot is listening. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
