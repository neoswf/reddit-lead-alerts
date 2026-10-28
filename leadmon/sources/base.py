import logging
from dataclasses import dataclass, field


@dataclass
class FetchContext:
    user_agent: str
    log: logging.Logger


@dataclass
class FetchResult:
    items: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    retry_after: int | None = None  # seconds; set when the source asked us to back off
