"""Reddit, through the public RSS feed Reddit publishes for new posts.

All of a source's subreddits are fetched as ONE combined feed (r/A+B+C/new/.rss), because
Reddit allows only a couple of quick requests before answering 429. Matching happens
locally, so we never use Reddit's search (which rate-limits harder).
"""
import html
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..models import Item
from .base import FetchResult

NAME = "reddit_rss"
FEED_URL = "https://www.reddit.com/r/{subs}/new/.rss?limit={limit}"
FEED_LIMIT = 100
ATOM = "{http://www.w3.org/2005/Atom}"
SUB_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
MAX_SUBREDDITS = 15
MIN_GAP_SECONDS = 10           # between any two Reddit requests from this process
DEFAULT_BACKOFF_SECONDS = 3600

_last_request = 0.0


def _wait_turn():
    """Space out requests when several clients or sources run in the same process."""
    global _last_request
    if _last_request:
        gap = time.monotonic() - _last_request
        if gap < MIN_GAP_SECONDS:
            time.sleep(MIN_GAP_SECONDS - gap)
    _last_request = time.monotonic()


def _sub_name(s: str) -> str:
    return s.strip().removeprefix("/").removeprefix("r/")


def validate(cfg: dict) -> list:
    subs = cfg.get("subreddits")
    if not isinstance(subs, list) or not subs:
        return ["a reddit_rss source needs a 'subreddits' list"]
    problems = [f"not a valid subreddit name: {s!r}" for s in subs
                if not isinstance(s, str) or not SUB_RE.match(_sub_name(s))]
    if len(subs) > MAX_SUBREDDITS:
        problems.append(f"{len(subs)} subreddits in one source; keep it to {MAX_SUBREDDITS} or fewer")
    return problems


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "li", "div", "tr"):
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(fragment: str) -> str:
    parser = _TextExtractor()
    parser.feed(fragment or "")
    text = " ".join("".join(parser.parts).split())
    # Reddit appends "submitted by /u/name [link] [comments]" to every entry.
    cut = text.rfind("submitted by")
    return text[:cut].strip() if cut != -1 else text


def parse_feed(body: bytes) -> list:
    root = ET.fromstring(body)
    items = []
    for entry in root.findall(f"{ATOM}entry"):
        entry_id = (entry.findtext(f"{ATOM}id") or "").strip()
        link = entry.find(f"{ATOM}link")
        url = link.get("href") if link is not None else ""
        stamp = (entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated") or "").strip()
        if not entry_id or not url or not stamp:
            continue
        try:
            published = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        category = entry.find(f"{ATOM}category")
        sub = category.get("term") if category is not None else "?"
        items.append(Item(
            id=f"reddit:{entry_id}",
            source=NAME,
            community=f"r/{sub}",
            title=html.unescape((entry.findtext(f"{ATOM}title") or "").strip()),
            text=html_to_text(entry.findtext(f"{ATOM}content") or ""),
            url=url,
            published=published,
        ))
    return items


def fetch(cfg: dict, ctx) -> FetchResult:
    result = FetchResult()
    subs = "+".join(_sub_name(raw) for raw in cfg["subreddits"])
    label = "r/" + subs
    _wait_turn()
    request = urllib.request.Request(
        FEED_URL.format(subs=subs, limit=FEED_LIMIT),
        headers={"User-Agent": ctx.user_agent, "Accept": "application/atom+xml"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = e.headers.get("Retry-After", "")
            result.retry_after = int(retry) if retry.isdigit() else DEFAULT_BACKOFF_SECONDS
            result.errors.append(f"{label}: Reddit says too many requests (429), backing off")
        elif e.code == 403:
            result.errors.append(f"{label}: Reddit refused the request (403)")
        elif e.code == 404:
            result.errors.append(f"{label}: not found; check the subreddit names (404)")
        else:
            result.errors.append(f"{label}: HTTP {e.code}")
        return result
    except (urllib.error.URLError, TimeoutError) as e:
        result.errors.append(f"{label}: network problem ({getattr(e, 'reason', e)})")
        return result
    try:
        result.items = parse_feed(body)
    except ET.ParseError as e:
        result.errors.append(f"{label}: the feed could not be read ({e})")
        return result

    ctx.log.info("%s: %d posts in feed", label, len(result.items))
    if len(result.items) >= FEED_LIMIT:
        span_hours = (datetime.now(timezone.utc) - min(i.published for i in result.items)).total_seconds() / 3600
        if span_hours < 1:
            result.errors.append(
                f"{label}: very busy feed ({FEED_LIMIT} posts in under an hour), some posts may be "
                "missed; split the subreddits into two [[sources]] blocks"
            )
    return result
