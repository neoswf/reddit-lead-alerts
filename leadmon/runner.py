"""One check for one client: fetch, skip what was seen, match, store, alert."""
import logging
from datetime import timedelta

from .matcher import match
from .notify import NotifyError, send_alert
from .sources import ADAPTERS
from .sources.base import FetchContext
from .store import utcnow

log = logging.getLogger("leadmon")

# Schedulers drift (GitHub's cron can start runs several minutes late, then the next one on
# time), so a run counts as due a little before the full interval has passed.
DUE_TOLERANCE = timedelta(minutes=10)
# Matches that could not be sent are retried on later runs, but only while still fresh.
ALERT_WINDOW = timedelta(hours=24)


def is_due(client, store) -> bool:
    last = store.last_run_started(client.slug)
    return last is None or utcnow() - last >= timedelta(minutes=client.interval_minutes) - DUE_TOLERANCE


def run_client(client, store, *, user_agent: str, test: bool = False, force: bool = False,
               channel: str | None = None) -> dict:
    """Returns a summary dict. Never raises for source or alert problems; they are logged."""
    if store.is_paused():
        log.info("Monitoring is paused for all clients. Run 'resume' to continue.")
        return {"status": "paused"}
    if client.paused or store.is_paused(client.slug):
        log.info("%s: paused, skipping.", client.name)
        return {"status": "paused"}
    if not (test or force or is_due(client, store)):
        log.info("%s: not due yet (every %d min).", client.name, client.interval_minutes)
        return {"status": "not-due"}

    run_id = store.start_run(client.slug)
    ctx = FetchContext(user_agent=user_agent, log=log)
    errors, fetched, new_items, matched = [], 0, 0, 0
    sources = [{"type": "fixture"}] if test else client.sources

    for src in sources:
        kind = src["type"]
        cooldown = store.cooldown_until(kind)
        if cooldown and cooldown > utcnow() and not test:
            errors.append(f"{kind}: backing off until {cooldown.astimezone():%H:%M} after a rate limit")
            continue

        result = ADAPTERS[kind].fetch(src, ctx)
        errors.extend(result.errors)
        if result.retry_after:
            store.set_cooldown(kind, utcnow() + timedelta(seconds=result.retry_after))

        fetched += len(result.items)
        for item in result.items:
            if store.is_seen(client.slug, item.id):
                continue
            new_items += 1
            if item.age_hours() > client.max_age_hours:
                store.mark_seen(client.slug, item.id)
                continue
            outcome = match(item, client)
            if outcome.matched and store.title_matched_recently(client.slug, item.title):
                log.info("%s: same post already alerted (cross-post) %s | %s", client.name, item.community, item.title[:80])
            elif outcome.matched:
                store.save_match(client, item, outcome.reason)
                matched += 1
                log.info("%s: MATCH %s | %s | %s", client.name, item.community, item.title[:80], outcome.reason)
            elif outcome.excluded_by:
                log.info("%s: excluded %s | %s | %s", client.name, item.community, item.title[:80], outcome.reason)
            store.mark_seen(client.slug, item.id)
        store.commit()

    sent = deliver_pending(client, store, channel=channel, test=test, errors=errors)
    store.finish_run(run_id, fetched=fetched, new_items=new_items, matches=matched,
                     alerts_sent=sent, errors=errors)
    for err in errors:
        log.warning("%s: %s", client.name, err)
    log.info("%s: checked %d posts, %d new, %d matches, %d alerts sent.",
             client.name, fetched, new_items, matched, sent)
    return {"status": "ok", "fetched": fetched, "new": new_items, "matches": matched,
            "sent": sent, "errors": errors}


def deliver_pending(client, store, *, channel=None, test=False, errors=None) -> int:
    """Send matches that have not been alerted yet, newest first, up to the per-run cap."""
    sent = 0
    for row in store.pending_alerts(client.slug, utcnow() - ALERT_WINDOW, client.max_alerts_per_run):
        try:
            send_alert(client, row, channel=channel, test=test)
        except NotifyError as e:
            if errors is not None:
                errors.append(f"alert not sent: {e}")
            break  # don't hammer a failing channel; the rest are retried next run
        store.mark_notified(row["id"])
        sent += 1
    return sent
