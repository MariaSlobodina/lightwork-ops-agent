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
            title="Ship AI Copilot v2 with multi-step tool use",
            description="GA release of the agent-powered copilot with multi-tool orchestration.",
            owner="Mikhail",
            deadline=_d(9),
            updates=[
                ("Mikhail", "Tool routing landed; running the eval suite this week.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        dict(
            team="Engineering",
            title="Migrate vector store to pgvector 0.7",
            description="Move from the managed vector DB to pgvector for cost and latency.",
            owner="Yevhen",
            deadline=_d(2),
            updates=[
                ("Yevhen", "Index rebuild slower than expected on the prod corpus — needs another 4 days.", "at_risk", 0),
            ],
            final_status="at_risk",
        ),
        dict(
            team="Engineering",
            title="Cut inference cost per request by 30%",
            description="Quarterly perf goal — prompt caching plus smaller models on cheap paths.",
            owner="Yevhen",
            deadline=_d(21),
            updates=[
                ("Yevhen", "Cache hit rate at 62%; cost per req down 22%. On pace.", "on_track", -2),
            ],
            final_status="on_track",
        ),
        dict(
            team="Engineering",
            title="Ship customer-facing audit log export",
            description="Compliance-required: customers can pull their own audit trail.",
            owner="Mikhail",
            deadline=_d(-2),
            updates=[
                ("Mikhail", "Backend done, UI shipped. Awaiting final compliance sign-off.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        # ---- Product ----
        dict(
            team="Product",
            title="Launch v2 onboarding with AI setup wizard",
            description="Replace the manual 4-step onboarding with an LLM-driven wizard.",
            owner="Anna",
            deadline=_d(14),
            updates=[
                ("Anna", "Flow prototyped, usability tests scheduled for Friday.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        dict(
            team="Product",
            title="Customer interview synthesis for H2 roadmap",
            description="22 customer interviews; themes feed into H2 planning.",
            owner="Anna",
            deadline=_d(4),
            updates=[],  # No updates logged — should trigger nudge
            final_status="on_track",
        ),
        dict(
            team="Product",
            title="Deprecate legacy reporting module",
            description="Sunset the old reports tab; migrate users to v2 reports.",
            owner="Anna",
            deadline=_d(-5),
            updates=[
                ("Anna", "Slipped — 4 enterprise accounts still haven't migrated.", "missed", -2),
            ],
            final_status="missed",
        ),
        # ---- Commercial ----
        dict(
            team="Commercial",
            title="Close Greenfield pilot to paid annual",
            description="Convert Greenfield Capital from pilot to a paid annual contract.",
            owner="Oleg",
            deadline=_d(11),
            updates=[
                ("Oleg", "Procurement greenlit; legal redlines this week.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        dict(
            team="Commercial",
            title="Hit £250k new ARR for the month",
            description="Monthly bookings target.",
            owner="Oleg",
            deadline=_d(7),
            updates=[
                ("Oleg", "At £142k committed, £105k in late-stage pipeline. Tight but doable.", "at_risk", -1),
            ],
            final_status="at_risk",
        ),
        dict(
            team="Commercial",
            title="Run partner webinar with Northstar",
            description="Joint webinar to drive top-of-funnel from Northstar's customer list.",
            owner="Oleg",
            deadline=_d(18),
            updates=[
                ("Oleg", "Date confirmed, registration page live, 168 signups so far.", "on_track", -1),
            ],
            final_status="on_track",
        ),
        # ---- Operations ----
        dict(
            team="Operations",
            title="Close SOC2 Type II observation window",
            description="External auditor sign-off at the end of the Type II window.",
            owner="Anna",
            deadline=_d(28),
            updates=[
                ("Anna", "Evidence collection 75% done; auditor walkthrough booked.", "on_track", -3),
            ],
            final_status="on_track",
        ),
        dict(
            team="Operations",
            title="Hire Senior BDR",
            description="Backfill for the BDR who left last month.",
            owner="Oleg",
            deadline=_d(1),
            updates=[],  # no updates, deadline tomorrow — strong nudge candidate
            final_status="on_track",
        ),
        dict(
            team="Operations",
            title="Renew cyber insurance policy",
            description="Existing policy lapses end of next quarter.",
            owner="Anna",
            deadline=_d(45),
            updates=[
                ("Anna", "Three brokers contacted, quotes due next week.", "on_track", -2),
            ],
            final_status="on_track",
        ),
        # A done item to show the flip side
        dict(
            team="Engineering",
            title="Migrate staging to managed Kubernetes",
            description="Replace the brittle staging env with a managed EKS cluster.",
            owner="Mikhail",
            deadline=_d(-10),
            updates=[
                ("Mikhail", "Done — fully migrated, green for a week.", "done", -7),
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
