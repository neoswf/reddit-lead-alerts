#!/usr/bin/env python3
"""Lead monitor command line. Run `python3 monitor.py --help` to see every command.

It only reads public feeds and alerts you. It never posts, comments, or messages anyone.
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from leadmon import config
from leadmon.config import ConfigError
from leadmon.notify import NotifyError, send_test_message, telegram
from leadmon.runner import run_client
from leadmon.sources import NETWORK_SOURCES
from leadmon.store import Store

LOOP_TICK_SECONDS = 60
log = logging.getLogger("leadmon")


def setup_logging():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(config.DATA_DIR / "monitor.log", maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(file_handler)
    log.addHandler(console)
    log.setLevel(logging.INFO)


def user_agent_for(clients) -> str:
    agent = os.environ.get("REDDIT_USER_AGENT", "").strip()
    needs_network = any(s["type"] in NETWORK_SOURCES for c in clients for s in c.sources)
    if needs_network and not agent:
        raise ConfigError(
            "REDDIT_USER_AGENT is missing. Add it as a GitHub secret (or to .env on your computer), e.g.\n"
            "  lead-monitor/0.1 (personal use; contact you@example.com)"
        )
    return agent or "lead-monitor/0.1"


def cmd_run(args):
    clients = config.load_clients(args.client)
    store = Store(config.db_path())
    agent = user_agent_for(clients)
    for client in clients:
        run_client(client, store, user_agent=agent, force=args.force, channel=args.channel)
    store.prune_seen()


def cmd_loop(args):
    store = Store(config.db_path())
    log.info("Monitoring started. Checks each client when it is due. Ctrl+C to stop.")
    try:
        while True:
            try:
                clients = config.load_clients(args.client)  # re-read so edits apply without a restart
                agent = user_agent_for(clients)
                for client in clients:
                    run_client(client, store, user_agent=agent, channel=args.channel)
                store.prune_seen()
            except ConfigError as e:
                log.error("Config problem, will retry in a minute: %s", e)
            except Exception:  # keep the loop alive; the log has the details
                log.exception("Unexpected error during a check")
            time.sleep(LOOP_TICK_SECONDS)
    except KeyboardInterrupt:
        log.info("Monitoring stopped.")


def cmd_test(args):
    """Offline: sample posts, a throwaway database, alerts printed here unless --telegram."""
    test_db = config.DATA_DIR / "test.db"
    test_db.unlink(missing_ok=True)
    store = Store(test_db)
    channel = None if args.telegram else "console"
    for client in config.load_clients(args.client):
        print(f"\n=== Test run for {client.name} (sample posts, nothing is fetched or contacted) ===")
        run_client(client, store, user_agent="test", test=True, channel=channel)


def cmd_test_notify(args):
    for client in config.load_clients(args.client):
        send_test_message(client, channel=args.channel)
        print(f"Test alert sent for {client.name} via {args.channel or client.notify['channel']}.")


def cmd_pause(args):
    Store(config.db_path()).set_paused(args.client, True)
    print(f"Paused {'client ' + args.client if args.client else 'all monitoring'}. Use 'resume' to continue.")


def cmd_resume(args):
    Store(config.db_path()).set_paused(args.client, False)
    print(f"Resumed {'client ' + args.client if args.client else 'all monitoring'}.")


def cmd_status(args):
    store = Store(config.db_path())
    print("All monitoring: " + ("PAUSED" if store.is_paused() else "running"))
    for client in config.load_clients(args.client):
        last = store.last_run_started(client.slug)
        paused = client.paused or store.is_paused(client.slug)
        subs = ", ".join(", ".join(s.get("subreddits", [s["type"]])) for s in client.sources)
        print(f"\n{client.name}  [{client.slug}]{'  PAUSED' if paused else ''}")
        print(f"  every {client.interval_minutes} min · alerts via {client.notify['channel']}")
        print(f"  watching: {subs}")
        print(f"  last check: {last.astimezone():%d %b %H:%M}" if last else "  last check: never")
    cooldown = store.cooldown_until("reddit_rss")
    if cooldown:
        print(f"\nReddit back-off until {cooldown.astimezone():%d %b %H:%M}")
    print(f"\nMatches: {store.status_counts()}")


def cmd_check(args):
    clients = config.load_clients(args.client)
    for client in clients:
        print(f"OK  {client.path.name}: {client.name}, {len(client.include)} include phrases, "
              f"{len(client.exclude)} exclude phrases, alerts via {client.notify['channel']}")
    user_agent_for(clients)
    print("OK  .env has what the sources need")


def cmd_telegram_chat_id(args):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is missing. Add it as a GitHub secret (or to .env on your computer) first.")
    chats = telegram.find_chats(token)
    if not chats:
        print("No messages found yet. Open your bot in Telegram, press Start or send it any message, then run this again.")
        return
    for chat_id, label in chats:
        print(f"{chat_id}    {label}")
    print("\nSave the number as TELEGRAM_CHAT_ID: a GitHub secret, or a line in .env on your computer.")


def cmd_summary(args):
    """Markdown list of recent matches and checks, for GitHub's run page."""
    store = Store(config.db_path())
    rows = [m for m in store.list_matches(limit=50)
            if datetime.fromisoformat(m["matched_at"]) > datetime.now(timezone.utc) - timedelta(hours=args.hours)]
    print(f"## Matches in the last {args.hours} hours ({len(rows)})\n")
    for m in rows:
        title = m["title"].replace("[", "(").replace("]", ")")
        print(f"- **{m['client_name']}** · {m['community']} · [{title}]({m['url']})  \n  _{m['reason']}_")
    if not rows:
        print("No matches.")
    print("\n## Recent checks\n\n| When (UTC) | Client | Posts read | New | Matches | Alerts | Problems |")
    print("|---|---|---|---|---|---|---|")
    for r in store.recent_runs(10):
        problems = (r["errors"] or "").replace("\n", "; ").replace("|", "/")
        print(f"| {r['started'][:16].replace('T', ' ')} | {r['client']} | {r['fetched']} | {r['new_items']} "
              f"| {r['matches']} | {r['alerts_sent']} | {problems} |")


def cmd_dashboard(args):
    from leadmon.dashboard import serve
    serve(Store(config.db_path()), args.port)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text, client=True, channel=False):
        p = sub.add_parser(name, help=help_text)
        if client:
            p.add_argument("--client", help="only this client (file name in clients/, without .toml)")
        if channel:
            p.add_argument("--channel", choices=config.CHANNELS, help="override the client's alert channel")
        p.set_defaults(func=func)
        return p

    add("run", cmd_run, "check once now (skips clients that are not due)", channel=True).add_argument(
        "--force", action="store_true", help="check even if the last check was recent")
    add("loop", cmd_loop, "keep checking on schedule until Ctrl+C", channel=True)
    add("test", cmd_test, "offline test with sample posts; nothing is fetched or contacted").add_argument(
        "--telegram", action="store_true", help="send the test alerts to Telegram instead of printing them")
    add("test-notify", cmd_test_notify, "send one sample alert to check your phone gets it", channel=True)
    add("pause", cmd_pause, "pause all monitoring, or one client with --client")
    add("resume", cmd_resume, "resume after a pause")
    add("status", cmd_status, "show clients, last checks and match counts")
    add("check", cmd_check, "validate client files and .env")
    add("telegram-chat-id", cmd_telegram_chat_id, "find your Telegram chat id after messaging your bot", client=False)
    add("summary", cmd_summary, "print recent matches as Markdown (used on GitHub)", client=False).add_argument(
        "--hours", type=int, default=24)
    add("dashboard", cmd_dashboard, "open the results page on this computer", client=False).add_argument(
        "--port", type=int, default=8765)

    args = parser.parse_args()
    config.load_env()
    setup_logging()
    try:
        args.func(args)
    except (ConfigError, NotifyError) as e:
        print(f"\nProblem: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
