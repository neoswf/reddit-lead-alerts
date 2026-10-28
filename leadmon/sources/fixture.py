"""Offline sample posts for test mode. Never touches the network."""
import json
from datetime import datetime, timedelta, timezone

from ..config import FIXTURES_DIR
from ..models import Item
from .base import FetchResult

NAME = "fixture"


def validate(cfg: dict) -> list:
    return []


def fetch(cfg: dict, ctx) -> FetchResult:
    path = FIXTURES_DIR / cfg.get("file", "sample_items.json")
    rows = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    items = [Item(
        id=f"fixture:{r['id']}",
        source=NAME,
        community=r["community"],
        title=r["title"],
        text=r["text"],
        url=r["url"],
        published=now - timedelta(hours=r["age_hours"]),
    ) for r in rows]
    ctx.log.info("fixture: %d sample posts from %s", len(items), path.name)
    return FetchResult(items=items)
