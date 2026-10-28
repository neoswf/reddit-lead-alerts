"""Telegram alerts through your own bot. Messages go only to the chat id you configure."""
import json
import time
import urllib.error
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"


class NotifyError(Exception):
    retry_after = None


def _call(token: str, method: str, payload: dict | None = None):
    # The token is part of the URL, so error messages below never include the URL.
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            raise NotifyError(f"Telegram answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise NotifyError(f"could not reach Telegram ({getattr(e, 'reason', e)})") from None
    if not body.get("ok"):
        error = NotifyError(f"Telegram refused: {body.get('description', 'unknown error')}")
        error.retry_after = (body.get("parameters") or {}).get("retry_after")
        raise error
    return body["result"]


def send(token: str, chat_id: str, html_text: str):
    payload = {
        "chat_id": chat_id,
        "text": html_text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        _call(token, "sendMessage", payload)
    except NotifyError as e:
        if not e.retry_after:
            raise
        time.sleep(min(int(e.retry_after), 60))
        _call(token, "sendMessage", payload)


def find_chats(token: str) -> list:
    """Chats that recently messaged the bot, so you can copy your chat id."""
    chats = {}
    for update in _call(token, "getUpdates"):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat")
        if chat:
            label = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])
            ) or chat.get("username", "")
            chats[chat["id"]] = f"{label} ({chat.get('type')})"
    return sorted(chats.items())
