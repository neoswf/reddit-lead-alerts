"""Loads secrets from .env and client settings from clients/*.toml."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "clients"
DATA_DIR = ROOT / "data"
FIXTURES_DIR = ROOT / "fixtures"

# Hard floor for how often a client's sources are checked. It lives in code on purpose,
# so a typo in a client file cannot make the tool hammer a website.
MIN_INTERVAL_MINUTES = 30

CHANNELS = ("telegram", "console")


class ConfigError(Exception):
    pass


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env into the environment. Real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def db_path() -> Path:
    return Path(os.environ.get("LEADMON_DB") or DATA_DIR / "leads.db")


@dataclass
class Client:
    slug: str
    name: str
    paused: bool
    interval_minutes: int
    sources: list
    include: list
    exclude: list
    max_age_hours: float
    location_terms: list
    location_required: bool
    service_type: str
    notify: dict
    path: Path

    @property
    def max_alerts_per_run(self) -> int:
        return int(self.notify.get("max_alerts_per_run", 10))


def _text_list(value, field_name: str, path: Path) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{path.name}: '{field_name}' must be a list of text values")
    return [v.strip() for v in value]


def load_client(path: Path) -> Client:
    from .sources import ADAPTERS  # imported here to avoid an import cycle

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: not valid TOML ({e})") from e

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{path.name}: 'name' is required")

    interval = int(data.get("schedule", {}).get("interval_minutes", MIN_INTERVAL_MINUTES))
    interval = max(interval, MIN_INTERVAL_MINUTES)

    sources = data.get("sources", [])
    if not sources:
        raise ConfigError(f"{path.name}: add at least one [[sources]] block")
    for src in sources:
        kind = src.get("type")
        if kind not in ADAPTERS:
            raise ConfigError(f"{path.name}: unknown source type {kind!r} (known: {', '.join(ADAPTERS)})")
        problems = ADAPTERS[kind].validate(src)
        if problems:
            raise ConfigError(f"{path.name}: " + "; ".join(problems))

    match = data.get("match", {})
    include = _text_list(match.get("include"), "match.include", path)
    if not include:
        raise ConfigError(f"{path.name}: 'match.include' needs at least one phrase")

    location = data.get("location", {})
    notify = data.get("notify", {})
    if notify.get("channel", "console") not in CHANNELS:
        raise ConfigError(f"{path.name}: notify.channel must be one of {', '.join(CHANNELS)}")
    notify.setdefault("channel", "console")

    return Client(
        slug=path.stem,
        name=name.strip(),
        paused=bool(data.get("paused", False)),
        interval_minutes=interval,
        sources=sources,
        include=include,
        exclude=_text_list(match.get("exclude"), "match.exclude", path),
        max_age_hours=float(match.get("max_age_hours", 12)),
        location_terms=_text_list(location.get("terms"), "location.terms", path),
        location_required=bool(location.get("required", False)),
        service_type=str(data.get("service_type", "")),
        notify=notify,
        path=path,
    )


def load_clients(only: str | None = None) -> list:
    """All active client files, or just one. Files starting with '_' are examples and are skipped."""
    if only:
        path = CLIENTS_DIR / f"{only.removesuffix('.toml')}.toml"
        if not path.exists():
            raise ConfigError(f"no client file at clients/{path.name}")
        return [load_client(path)]
    files = sorted(p for p in CLIENTS_DIR.glob("*.toml") if not p.name.startswith("_"))
    if not files:
        raise ConfigError("no client files in clients/ (files starting with '_' are examples)")
    return [load_client(p) for p in files]
