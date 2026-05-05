"""Proactive risk scan.

Runs in two ways:
- On every Streamlit page load (cheap; the ``needs_attention`` query is just SQL).
- Once a day via APScheduler (in-process), which auto-promotes commitments to
  ``at_risk`` when their deadline is close and there's been no update.

Promotions are recorded in the ``nudges`` table so we don't re-flag the same
commitment day after day.
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import db

log = logging.getLogger(__name__)


def scan_and_flag() -> list[dict]:
    """Promote at-risk candidates and return the list of items just flagged.

    Rules:
    - If a commitment is past its deadline and not done -> mark missed.
    - If deadline within 3 days, no update in 4+ days, status still on_track ->
      promote to at_risk and record a nudge.
    """
    flagged: list[dict] = []

    # First, capture which open commitments are past deadline so we can record
    # nudges for them — then run the bulk auto-flip.
    candidates = [
        c for c in db.list_commitments(include_done=False)
        if db.days_until_deadline(c["deadline"]) < 0
        and c["status"] not in ("done", "missed")
    ]
    if candidates:
        db.auto_mark_missed_past_deadlines()
        for c in candidates:
            days_left = db.days_until_deadline(c["deadline"])
            reason = f"Auto-flagged missed: deadline passed {abs(days_left)}d ago"
            db.record_nudge(c["id"], reason)
            flagged.append({**c, "status": "missed", "_reason": reason})

    for c in db.list_commitments(include_done=False):
        days_left = db.days_until_deadline(c["deadline"])
        stale = db.days_since_last_update(c)

        if (
            c["status"] == "on_track"
            and 0 <= days_left <= 3
            and (stale is None or stale >= 4)
        ):
            if not db.recent_nudge_exists(c["id"], hours=20):
                db.set_status(c["id"], "at_risk")
                reason = (
                    f"Auto-flagged at_risk: deadline in {days_left}d, "
                    f"{'no updates' if stale is None else f'last update {stale}d ago'}"
                )
                db.record_nudge(c["id"], reason)
                flagged.append({**c, "_reason": reason})

    if flagged:
        log.info("Proactive scan flagged %d commitment(s) at %s", len(flagged), datetime.now())
    return flagged


_scheduler: BackgroundScheduler | None = None


def start_background_scheduler() -> None:
    """Start a daily scan in the same process as the Streamlit app.

    Idempotent — safe to call on every Streamlit reload (we keep one scheduler
    per process via the module-level singleton).
    """
    global _scheduler
    if _scheduler is not None:
        return
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(scan_and_flag, "cron", hour=8, minute=0, id="daily_risk_scan")
    sched.start()
    _scheduler = sched
    log.info("LightWork ops scheduler started — daily scan at 08:00 local time.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    flagged = scan_and_flag()
    print(f"Flagged {len(flagged)} commitment(s).")
    for f in flagged:
        print(f" - [{f['team']}] {f['title']} :: {f['_reason']}")
