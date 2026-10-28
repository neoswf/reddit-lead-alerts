from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Item:
    """One post from any source, in the same shape whatever the source is."""

    id: str          # stable and unique across sources, e.g. "reddit:t3_abc123"
    source: str      # adapter name, e.g. "reddit_rss"
    community: str   # where it was posted, e.g. "r/smallbusiness"
    title: str
    text: str        # full body, used for matching only and never stored
    url: str
    published: datetime

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.published).total_seconds() / 3600
