"""Alert channels.

Every channel sends only to you. Nothing in this tool contacts the people who wrote the posts.
"""
import html
import os
from datetime import datetime, timezone

from . import telegram
from .telegram import NotifyError

__all__ = ["NotifyError", "send_alert", "send_test_message", "telegram_credentials"]


def _age(published_iso: str) -> str:
    minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(published_iso)).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} min old"
    hours = minutes // 60
    return f"{hours} h old" if hours < 48 else f"{hours // 24} days old"


def format_alert(client_name: str, row, *, as_html: bool, test: bool = False) -> str:
    e = html.escape if as_html else (lambda s, quote=True: s)
    prefix = "[TEST] " if test else ""
    header = f"{prefix}{e(client_name)} · {e(row['community'])} · {_age(row['published'])}"
    title = e(row["title"])
    parts = [f"<b>{header}</b>" if as_html else header, f"<b>{title}</b>" if as_html else title]
    if row["excerpt"]:
        parts.append(e(row["excerpt"]))
    why = f"Why: {e(row['reason'])}"
    parts.append(f"<i>{why}</i>" if as_html else why)
    if as_html:
        parts.append(f'<a href="{html.escape(row["url"], quote=True)}">Open the post</a>')
    else:
        parts.append(row["url"])
    return "\n\n".join(parts)


def telegram_credentials(client) -> tuple:
    token_env = client.notify.get("token_env", "TELEGRAM_BOT_TOKEN")
    chat_env = client.notify.get("chat_id_env", "TELEGRAM_CHAT_ID")
    token, chat_id = os.environ.get(token_env), os.environ.get(chat_env)
    missing = [name for name, value in ((token_env, token), (chat_env, chat_id)) if not value]
    if missing:
        raise NotifyError(f"missing: {', '.join(missing)}. Add it as a GitHub secret, or to .env on your computer (see README).")
    return token, chat_id


def _deliver(client, text_html: str, text_plain: str, channel: str):
    if channel == "console":
        print("\n" + "-" * 60 + "\n" + text_plain + "\n" + "-" * 60)
    elif channel == "telegram":
        token, chat_id = telegram_credentials(client)
        telegram.send(token, chat_id, text_html)
    else:
        raise NotifyError(f"unknown channel {channel!r}")


def send_alert(client, row, *, channel: str | None = None, test: bool = False):
    channel = channel or client.notify["channel"]
    _deliver(
        client,
        format_alert(client.name, row, as_html=True, test=test),
        format_alert(client.name, row, as_html=False, test=test),
        channel,
    )


def send_test_message(client, channel: str | None = None):
    sample = {
        "community": "r/example",
        "published": datetime.now(timezone.utc).isoformat(),
        "title": "Test alert: if you can read this, alerts work",
        "excerpt": "This is a sample message from the lead monitor. No post was found and nobody was contacted.",
        "reason": 'matched "test" in title',
        "url": "https://example.com/",
    }
    send_alert(client, sample, channel=channel, test=True)
