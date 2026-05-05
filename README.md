# LightWork Ops Agent

A working prototype of an **operations orchestration agent** for LightWork AI.
It helps a Founder's Associate keep every team's commitments and deadlines
visible, flags what's at risk, and writes the weekly cross-team summary so
the co-founders never miss a slipping deadline.

The app opens with a pre-seeded snapshot of ~14 realistic LightWork
commitments across Engineering, Product, Commercial and Operations — so you
can interact with it the moment it loads.

---

## 1-page brief

### What I built
A single-page web app (Streamlit) backed by a SQLite database and an OpenAI
agent. It does four things end-to-end:

1. **Ingests commitments** — either through a form or by typing in plain
   English ("Engineering is shipping the Stripe integration by 14 May,
   owner Priya"). The agent extracts team, title, deadline, and owner.
2. **Tracks status** — every commitment is `on_track`, `at_risk`, `missed`,
   or `done`. Anyone can post an update; the agent classifies the wording.
3. **Generates a weekly summary** — one click produces a short markdown
   exec summary across all four teams: wins, at-risk items, quiet ones
   (no recent updates), and concrete asks for the founders.
4. **Proactively flags risk** — a daily background scan auto-promotes
   commitments to `at_risk` when their deadline is close and there's been
   no update, and to `missed` when the deadline has passed without a
   `done` status. A "Needs attention" panel surfaces these the moment the
   FA opens the app.

### Tools used and why
- **Streamlit** — fastest path to a usable, hosted UI for non-technical
  users. Free hosting on Streamlit Community Cloud means I can hand over a
  shareable URL with no infra setup.
- **OpenAI `gpt-4o` with function calling** — the model orchestrates seven
  tools (`add_commitment`, `log_update`, `set_status`, `list_commitments`,
  `get_at_risk`, `generate_weekly_summary`). Function calling keeps the
  agent honest: it can only mutate state through the same DB layer the UI
  uses, so chat-driven changes and form-driven changes are guaranteed to
  produce identical results.
- **SQLite** — single file, zero ops, trivial to seed for the demo and to
  back up.
- **APScheduler** — runs the daily proactive scan in the same process as
  the Streamlit app. No extra worker or cron host needed for a prototype.

### How a user would interact day-to-day
- **Morning:** open the app. The "Needs attention" panel lists everything
  that's drifted overnight (deadlines passed, no-update-in-N-days, etc.).
- **During the week:** drop new commitments in via chat as they're decided
  in stand-ups (no form-filling required). Owners (or the FA on their
  behalf) log updates against existing commitments — also via chat or via
  the dashboard form.
- **Friday:** click *Generate weekly summary*. Copy the output into the
  weekly all-hands doc or email it to the co-founders.

### What I'd improve with more time
- **Slack ingestion + nudges.** Read commitments from a #ops channel and
  DM owners directly when their item goes quiet, so the FA isn't the
  middleman.
- **Linear/Jira/HubSpot connectors** to auto-update Engineering and
  Commercial commitments from system-of-record signals (PR merged, deal
  stage changed) instead of relying on humans to log updates.
- **Multi-user auth + per-team views** — currently anyone with the URL
  can edit anything; fine for a prototype, not for production.
- **Confidence + reasoning trace** on agent classifications so the FA can
  audit *why* the agent thinks something is at risk.
- **Trend memory** — track how often each team hits/misses, so the
  weekly summary can call out chronic patterns, not just this-week
  status.

### Limitations
- Single-tenant, single-DB-file prototype; not production-hardened
  (no auth, no row-level permissions, no audit log).
- The agent's status classification is best-effort; the FA can always
  override with the manual status dropdown.
- The scheduled scan runs in-process — if Streamlit's container is
  recycled, the timer resets (next page load still triggers the cheap
  attention check, so users won't see stale data).
- API costs scale with chat volume — a real deployment would want
  prompt caching and a cheaper model for routine extraction.

---

## Run it locally

```bash
# 1. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure your OpenAI key
cp .env.example .env
# then edit .env to add your OPENAI_API_KEY

# 3. Seed the demo DB (optional — happens automatically on first launch)
python seed.py

# 4. Run
streamlit run app.py
```

The app runs at http://localhost:8501 (or whichever port Streamlit picks).

## Deploy to Streamlit Community Cloud

1. Push this directory to a GitHub repo.
2. Go to https://share.streamlit.io and connect the repo.
3. Set the entry point to `app.py`.
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   OPENAI_API_KEY = "sk-..."
   OPENAI_MODEL   = "gpt-4o"
   ```
5. Deploy. Share the URL with whoever needs to use it.

## Project layout

```
app.py          # Streamlit UI: Dashboard / Chat / Weekly summary tabs
agent.py        # OpenAI agent + tool definitions + weekly summary generator
db.py           # SQLite schema, CRUD helpers, needs-attention heuristic
scheduler.py    # Background daily scan that auto-flags at-risk / missed
seed.py         # Realistic demo commitments across all four teams
requirements.txt
.env.example
.streamlit/secrets.toml.example
```

## Resetting the demo

Click **Reset demo data** in the sidebar, or run `python seed.py` to wipe
and re-seed the SQLite file.
