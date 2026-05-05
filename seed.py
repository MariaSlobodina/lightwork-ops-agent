"""Seed the LightWork demo DB with realistic, varied commitments.

Uses today's date as the anchor so the demo always shows a mix of green,
amber, red, and recently-completed items relative to "now".
"""
from __future__ import annotations

from datetime import date, timedelta

from db import (
    DB_PATH,
    add_commitment,
    init_db,
    log_update,
    reset_db,
)


def _d(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def seed(force: bool = False) -> None:
    """Wipe and re-seed the DB with a realistic LightWork-style snapshot."""
    if force or not DB_PATH.exists():
        reset_db()
    init_db()

    items = [
        # ---- Engineering ----
        dict(
            team="Engineering",
            title="Ship Stripe billing integration",
            description="End-to-end Stripe checkout + webhook handling for paid plans.",
            owner="Priya",
            deadline=_d(9),
            updates=[
                ("Priya", "Webhook plumbing done; checkout flow QA next week.", "on_track", -2),
            ],
            final_status="on_track",
        ),
        dict(
            team="Engineering",
            title="Migrate auth service to new identity provider",
            description="Replace legacy auth with WorkOS; backfill SSO for pilot customers.",
            owner="Marcus",
            deadline=_d(2),
            updates=[
                ("Marcus", "Hit a snag with SAML metadata for Greenfield. Needs another 3 days minimum.", "at_risk", -1),
            ],
            final_status="at_risk",
        ),
        dict(
            team="Engineering",
            title="Reduce p95 API latency below 400ms",
            description="Quarterly perf goal across the public API surface.",
            owner="Marcus",
            deadline=_d(21),
            updates=[
                ("Marcus", "p95 down from 720ms to 510ms after caching layer.", "on_track", -4),
            ],
            final_status="on_track",
        ),
        dict(
            team="Engineering",
            title="Roll out audit log export",
            description="SOC2-required: customer-facing audit log download.",
            owner="Priya",
            deadline=_d(-2),
            updates=[
                ("Priya", "Backend done, UI shipped. Just needs final compliance sign-off.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        # ---- Product ----
        dict(
            team="Product",
            title="Launch v2 onboarding flow",
            description="New 4-step guided onboarding to lift activation rate.",
            owner="Sara",
            deadline=_d(14),
            updates=[
                ("Sara", "Designs locked, dev kickoff Monday.", "on_track", -3),
            ],
            final_status="on_track",
        ),
        dict(
            team="Product",
            title="Customer interview synthesis for Q2 roadmap",
            description="20 customer interviews, themes feed into Q2 planning.",
            owner="Sara",
            deadline=_d(4),
            updates=[],  # No updates logged — should trigger nudge
            final_status="on_track",
        ),
        dict(
            team="Product",
            title="Deprecate legacy reporting module",
            description="Sunset the old reports tab; migrate users to v2 reports.",
            owner="Sara",
            deadline=_d(-5),
            updates=[
                ("Sara", "Slipped — last 6 enterprise accounts haven't migrated yet.", "missed", -3),
            ],
            final_status="missed",
        ),
        # ---- Commercial ----
        dict(
            team="Commercial",
            title="Close Greenfield pilot",
            description="Convert Greenfield Capital from pilot to paid annual contract.",
            owner="James",
            deadline=_d(11),
            updates=[
                ("James", "Legal review in progress, exec sponsor confirmed.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        dict(
            team="Commercial",
            title="Hit £200k new ARR for the month",
            description="Monthly bookings target.",
            owner="James",
            deadline=_d(7),
            updates=[
                ("James", "At £128k committed, £90k in late-stage pipeline. Tight but doable.", "at_risk", -2),
            ],
            final_status="at_risk",
        ),
        dict(
            team="Commercial",
            title="Run partner webinar with Northstar",
            description="Joint webinar to drive top-of-funnel from Northstar's customer list.",
            owner="Aisha",
            deadline=_d(18),
            updates=[
                ("Aisha", "Date confirmed, registration page live, 142 signups so far.", "on_track", -2),
            ],
            final_status="on_track",
        ),
        # ---- Operations ----
        dict(
            team="Operations",
            title="Complete SOC2 Type I readiness audit",
            description="External auditor pre-assessment ahead of Type I window.",
            owner="Tom",
            deadline=_d(28),
            updates=[
                ("Tom", "Policies approved; evidence collection 60% done.", "on_track", -5),
            ],
            final_status="on_track",
        ),
        dict(
            team="Operations",
            title="Hire Senior BDR",
            description="Backfill for the BDR who left last month.",
            owner="Tom",
            deadline=_d(1),
            updates=[],  # no updates, deadline tomorrow — strong nudge candidate
            final_status="on_track",
        ),
        dict(
            team="Operations",
            title="Renew cyber insurance policy",
            description="Existing policy lapses end of next quarter.",
            owner="Tom",
            deadline=_d(45),
            updates=[
                ("Tom", "Three brokers contacted, quotes due next week.", "on_track", -2),
            ],
            final_status="on_track",
        ),
        # A done item to show the flip side
        dict(
            team="Engineering",
            title="Spin up staging cluster on new infra",
            description="Replace the brittle old staging env with a managed cluster.",
            owner="Priya",
            deadline=_d(-10),
            updates=[
                ("Priya", "Done — fully migrated, green for a week.", "done", -7),
            ],
            final_status="done",
        ),
    ]

    for item in items:
        # If there are no updates, insert with the final status directly so
        # last_update_at stays NULL (signal of "no one has logged anything").
        # If there are updates, the last update sets the status.
        initial_status = item["final_status"] if not item["updates"] else "on_track"
        cid = add_commitment(
            team=item["team"],
            title=item["title"],
            description=item["description"],
            owner=item["owner"],
            deadline=item["deadline"],
            status=initial_status,
        )
        for author, text, status, _days_ago in item["updates"]:
            log_update(cid, text=text, author=author, status_inferred=status)


if __name__ == "__main__":
    seed(force=True)
    print(f"Seeded demo DB at {DB_PATH}")
