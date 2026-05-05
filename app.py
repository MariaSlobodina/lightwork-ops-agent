"""Streamlit app — the LightWork Ops Agent UI.

Three tabs:
- Dashboard: see every team's commitments at a glance, plus a "needs attention" panel.
- Chat: talk to the agent in natural language to add commitments, log updates, ask questions.
- Weekly Summary: one-click executive write-up across all teams.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import agent
import db
from scheduler import scan_and_flag, start_background_scheduler
from seed import seed as seed_demo


# ---------- Setup ----------
st.set_page_config(
    page_title="LightWork Ops Agent",
    page_icon="🛰️",
    layout="wide",
)

# Pull OPENAI_API_KEY from Streamlit secrets into the process env when running
# on Streamlit Cloud (where there's no .env file). Locally, agent.py already
# loaded .env via dotenv on import, so we skip touching st.secrets entirely —
# accessing it without a secrets.toml file emits a UI warning banner.
_SECRETS_PATHS = [
    Path.home() / ".streamlit" / "secrets.toml",
    Path(__file__).parent / ".streamlit" / "secrets.toml",
]
if not os.getenv("OPENAI_API_KEY") and any(p.exists() for p in _SECRETS_PATHS):
    try:
        secrets = dict(st.secrets)
    except Exception:
        secrets = {}
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        if key in secrets and not os.getenv(key):
            os.environ[key] = secrets[key]

db.init_db()
# First-run convenience: seed demo data if the DB is empty.
if not db.list_commitments():
    seed_demo(force=False)

# Keep status badges honest on every page load: anything past its deadline
# that isn't done flips to 'missed' immediately (not just at the next scan).
db.auto_mark_missed_past_deadlines()

start_background_scheduler()


# ---------- Helpers ----------
STATUS_BADGE = {
    "on_track": ("🟢", "On track"),
    "at_risk": ("🟠", "At risk"),
    "missed": ("🔴", "Missed"),
    "done": ("✅", "Done"),
}


def status_label(status: str) -> str:
    icon, label = STATUS_BADGE.get(status, ("⚪️", status))
    return f"{icon} {label}"


def commitments_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=["Status", "Team", "Title", "Owner", "Deadline", "Days left", "Last update"]
        )
    today = date.today()
    out = []
    for c in rows:
        days_left = (datetime.strptime(c["deadline"], "%Y-%m-%d").date() - today).days
        last = c.get("last_update_at")
        if last:
            last_dt = datetime.fromisoformat(last)
            last_str = f"{(datetime.now() - last_dt).days}d ago"
        else:
            last_str = "—"
        out.append(
            {
                "Status": status_label(c["status"]),
                "Team": c["team"],
                "Title": c["title"],
                "Owner": c.get("owner") or "—",
                "Deadline": c["deadline"],
                "Days left": days_left,
                "Last update": last_str,
                "_id": c["id"],
            }
        )
    return pd.DataFrame(out)


# ---------- Sidebar ----------
with st.sidebar:
    st.title("🛰️ LightWork Ops")
    st.caption("Your operations co-pilot.")
    st.divider()

    counts = {s: 0 for s in db.STATUSES}
    for c in db.list_commitments():
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    st.metric("On track", counts["on_track"])
    st.metric("At risk", counts["at_risk"])
    st.metric("Missed", counts["missed"])
    st.metric("Done", counts["done"])

    st.divider()
    st.subheader("Maintenance")
    if st.button("Run risk scan now", use_container_width=True):
        flagged = scan_and_flag()
        if flagged:
            st.success(f"Flagged {len(flagged)} commitment(s).")
        else:
            st.info("Nothing new to flag — all clear.")

    if st.button("Reset demo data", use_container_width=True):
        seed_demo(force=True)
        st.success("Demo data reset.")
        st.rerun()

    st.divider()
    st.caption(f"Today: {date.today().isoformat()}")


# ---------- Tabs ----------
tab_dash, tab_chat, tab_summary = st.tabs(
    ["📋 Dashboard", "💬 Chat with the agent", "📰 Weekly summary"]
)


def render_detail_view(commitment_id: int) -> None:
    """Focused per-commitment 'page' — shown inside the Dashboard tab."""
    c = db.get_commitment(commitment_id)
    if not c:
        st.warning("That commitment no longer exists.")
        if st.button("← Back to dashboard"):
            st.session_state.pop("selected_commitment", None)
            st.rerun()
        return

    if st.button("← Back to dashboard"):
        st.session_state.pop("selected_commitment", None)
        st.rerun()

    days_left = (datetime.strptime(c["deadline"], "%Y-%m-%d").date() - date.today()).days
    last_update_at = c.get("last_update_at")
    if last_update_at:
        last_str = f"{(datetime.now() - datetime.fromisoformat(last_update_at)).days}d ago"
    else:
        last_str = "never"

    st.header(f"{c['team']} — {c['title']}")
    meta_cols = st.columns(4)
    meta_cols[0].markdown(f"**Status**  \n{status_label(c['status'])}")
    meta_cols[1].markdown(f"**Owner**  \n{c.get('owner') or '—'}")
    meta_cols[2].markdown(
        f"**Deadline**  \n{c['deadline']}  \n_{days_left:+d} days_"
    )
    meta_cols[3].markdown(f"**Last update**  \n{last_str}")

    if c.get("description"):
        st.markdown(f"> {c['description']}")

    st.divider()

    # Two-column layout: edit on the left, history on the right
    edit_col, hist_col = st.columns([0.55, 0.45])

    with edit_col:
        st.subheader("Log an update")
        with st.form(f"detail_update_{commitment_id}", clear_on_submit=True):
            author = st.text_input("Your name")
            text = st.text_area("What's the latest?", height=120)
            infer = st.checkbox(
                "Let the agent infer status from the text", value=True
            )
            manual_status = st.selectbox(
                "...or set status manually",
                ["(no change)", *db.STATUSES],
            )
            if st.form_submit_button("Log update", use_container_width=True):
                if not text.strip():
                    st.error("Update text is required.")
                else:
                    status = None
                    if manual_status != "(no change)":
                        status = manual_status
                    elif infer:
                        try:
                            status = agent.classify_update_status(c, text.strip())
                        except Exception as e:
                            st.warning(f"Status inference failed: {e}")
                    db.log_update(
                        commitment_id=commitment_id,
                        text=text.strip(),
                        author=author.strip() or None,
                        status_inferred=status,
                    )
                    msg = "Update logged."
                    if status:
                        msg += f" Status set to **{status_label(status)}**."
                    st.success(msg)
                    st.rerun()

        st.subheader("Change status")
        new_status = st.selectbox(
            "Status",
            db.STATUSES,
            index=db.STATUSES.index(c["status"]),
            key=f"status_select_{commitment_id}",
        )
        cols = st.columns([0.5, 0.5])
        if cols[0].button(
            "Save status", use_container_width=True, key=f"save_status_{commitment_id}"
        ):
            if new_status != c["status"]:
                db.set_status(commitment_id, new_status)
                st.success(f"Status set to {status_label(new_status)}.")
                st.rerun()
            else:
                st.info("Status unchanged.")
        if cols[1].button(
            "Mark as done ✅",
            use_container_width=True,
            type="primary",
            key=f"mark_done_{commitment_id}",
        ):
            db.set_status(commitment_id, "done")
            st.success("Marked as done.")
            st.rerun()

        st.subheader("Change deadline")
        st.caption(
            "Extending a missed deadline will auto-restore the status to on_track."
        )
        new_deadline = st.date_input(
            "New deadline",
            value=datetime.strptime(c["deadline"], "%Y-%m-%d").date(),
            key=f"deadline_input_{commitment_id}",
        )
        if st.button(
            "Save new deadline",
            use_container_width=True,
            key=f"save_deadline_{commitment_id}",
        ):
            new_iso = new_deadline.isoformat()
            if new_iso == c["deadline"]:
                st.info("Deadline unchanged.")
            else:
                result = db.update_deadline(commitment_id, new_iso)
                msg = (
                    f"Deadline changed from **{result['old_deadline']}** "
                    f"to **{result['new_deadline']}**."
                )
                if result["status_restored"]:
                    msg += f" Status restored to {status_label('on_track')}."
                st.success(msg)
                st.rerun()

    with hist_col:
        st.subheader("Update history")
        updates = db.list_updates(commitment_id)
        if not updates:
            st.caption("No updates logged yet.")
        for u in updates:
            with st.container(border=True):
                header_bits = [
                    f"**{u.get('author') or 'Anon'}**",
                    u["created_at"],
                ]
                if u.get("status_inferred"):
                    header_bits.append(
                        f"→ {status_label(u['status_inferred'])}"
                    )
                st.markdown(" · ".join(header_bits))
                st.write(u["text"])


def render_dashboard_list() -> None:
    """The default Dashboard view: attention panel + by-team table + add form."""
    st.header("Team performance")
    st.caption(
        "Everything LightWork has committed to. The agent flags anything that needs attention."
    )

    # Needs attention panel
    attention = db.needs_attention()
    if attention:
        with st.container(border=True):
            st.subheader(f"⚠️ Needs attention ({len(attention)})")
            for c in attention:
                cols = st.columns([0.7, 0.3])
                with cols[0]:
                    st.markdown(
                        f"**{status_label(c['status'])} · {c['team']} — {c['title']}**  \n"
                        f"Owner: {c.get('owner') or '—'} · Deadline: {c['deadline']} "
                        f"({c['_days_left']:+d}d) · _{c['_attention_reason']}_"
                    )
                with cols[1]:
                    if st.button(
                        "Open",
                        key=f"open_att_{c['id']}",
                        use_container_width=True,
                    ):
                        st.session_state["selected_commitment"] = c["id"]
                        st.rerun()
    else:
        st.success("Nothing needs attention right now. ✨")

    st.divider()

    # Filters
    filter_cols = st.columns([0.45, 0.4, 0.15])
    with filter_cols[0]:
        team_filter = st.multiselect("Filter by team", db.TEAMS, default=db.TEAMS)
    with filter_cols[1]:
        date_range = st.date_input(
            "Deadline between",
            value=(),
            help="Pick a start and end date to only show commitments whose deadlines fall in that window. Leave empty for no date filter.",
        )
    with filter_cols[2]:
        st.write("")  # vertical spacer to align with the date_input label
        show_done = st.checkbox("Show completed", value=False)

    rows = [
        c for c in db.list_commitments(include_done=show_done)
        if c["team"] in team_filter
    ]
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start_d, end_d = date_range
        rows = [
            c for c in rows
            if start_d
            <= datetime.strptime(c["deadline"], "%Y-%m-%d").date()
            <= end_d
        ]
        st.caption(
            f"Showing {len(rows)} commitment(s) with deadlines between "
            f"{start_d.isoformat()} and {end_d.isoformat()}. "
            f"_The attention panel above always shows everything._"
        )

    if not rows:
        st.info("No commitments match the current filter.")
    else:
        df = commitments_dataframe(rows)
        st.dataframe(
            df.drop(columns=["_id"]),
            hide_index=True,
            use_container_width=True,
        )

        # Quick-open dropdown for any row in the table
        options = {
            f"#{c['id']} · [{c['team']}] {c['title']}": c["id"] for c in rows
        }
        open_cols = st.columns([0.7, 0.3])
        with open_cols[0]:
            chosen_label = st.selectbox(
                "Open a commitment",
                list(options.keys()),
                index=None,
                placeholder="Pick a commitment to view or edit…",
                label_visibility="collapsed",
            )
        with open_cols[1]:
            if st.button(
                "Open",
                use_container_width=True,
                disabled=chosen_label is None,
                key="open_from_table",
            ):
                st.session_state["selected_commitment"] = options[chosen_label]
                st.rerun()

    st.divider()

    # Add a commitment
    st.subheader("Add a commitment")
    with st.form("add_form", clear_on_submit=True):
        cols = st.columns(2)
        team = cols[0].selectbox("Team", db.TEAMS)
        owner = cols[1].text_input("Owner (optional)")
        title = st.text_input("Title")
        deadline = st.date_input(
            "Deadline",
            value=date.today() + timedelta(days=14),
            min_value=date.today() - timedelta(days=365),
        )
        description = st.text_area("Description (optional)", height=80)
        if st.form_submit_button("Add commitment", use_container_width=True):
            if not title.strip():
                st.error("Title is required.")
            else:
                cid = db.add_commitment(
                    team=team,
                    title=title.strip(),
                    deadline=deadline.isoformat(),
                    owner=owner.strip() or None,
                    description=description.strip() or None,
                )
                st.success(f"Added commitment #{cid}.")
                st.rerun()


# ===== Dashboard =====
with tab_dash:
    if "selected_commitment" in st.session_state:
        render_detail_view(st.session_state["selected_commitment"])
    else:
        render_dashboard_list()


# ===== Chat =====
with tab_chat:
    st.header("Talk to the agent")
    st.caption(
        "Add commitments, log updates, or ask what's at risk — in plain English. "
        "The agent uses tools to read and write the same database the dashboard shows."
    )

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = agent.new_conversation()

    # Render the visible part of the transcript (skip system + tool plumbing)
    for m in st.session_state.chat_messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            continue
        if m["role"] == "assistant" and not m.get("content") and m.get("tool_calls"):
            # Pure tool-call turn — show a compact note instead of an empty bubble
            with st.chat_message("assistant"):
                tools_used = ", ".join(tc["function"]["name"] for tc in m["tool_calls"])
                st.caption(f"🔧 calling: {tools_used}")
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_input = st.chat_input("e.g. 'Engineering is shipping the Stripe integration by 14 May, owner Priya'")
    if user_input:
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply, updated = agent.run_chat(st.session_state.chat_messages)
                except Exception as e:
                    reply = f"Sorry — agent error: {e}"
                    updated = st.session_state.chat_messages
            st.session_state.chat_messages = updated
            st.markdown(reply)

    if st.button("Clear conversation"):
        st.session_state.chat_messages = agent.new_conversation()
        st.rerun()


# ===== Weekly summary =====
with tab_summary:
    st.header("Weekly summary")
    st.caption("Generates an executive-ready summary across all four teams using the latest data.")

    if "weekly_summary" not in st.session_state:
        st.session_state.weekly_summary = None
        st.session_state.weekly_summary_at = None

    cols = st.columns([0.3, 0.7])
    with cols[0]:
        if st.button("Generate weekly summary", type="primary", use_container_width=True):
            with st.spinner("Writing summary…"):
                try:
                    st.session_state.weekly_summary = agent.generate_weekly_summary()
                    st.session_state.weekly_summary_at = datetime.now().isoformat(
                        timespec="minutes"
                    )
                except Exception as e:
                    st.error(f"Couldn't generate summary: {e}")

    if st.session_state.weekly_summary:
        st.caption(f"Generated at {st.session_state.weekly_summary_at}")
        st.markdown(st.session_state.weekly_summary)
        st.download_button(
            "Download as markdown",
            data=st.session_state.weekly_summary,
            file_name=f"lightwork-weekly-{date.today().isoformat()}.md",
            mime="text/markdown",
        )
    else:
        st.info("Click the button above to generate this week's summary.")
