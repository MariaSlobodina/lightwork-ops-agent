"""OpenAI-powered orchestration agent for LightWork Ops.

The agent is a thin loop on top of OpenAI Chat Completions with function
calling. All state lives in SQLite (db.py); the agent only reads/writes via
the tools defined here, so the same tools also power the Streamlit UI.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Iterable

from dotenv import load_dotenv
from openai import OpenAI

import db

load_dotenv()

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env (local) or "
                "Streamlit secrets (deployed)."
            )
        _client = OpenAI(api_key=api_key)
    return _client


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")


def _system_prompt() -> str:
    return f"""You are the LightWork Ops Agent. You help a Founder's Associate at \
LightWork AI (a 20-30 person startup with Engineering, Product, Commercial and \
Operations teams) keep track of every team's commitments and deadlines.

Today's date is {date.today().isoformat()}.

Your job:
- Capture new commitments accurately when described in natural language. Always \
extract: team, title, deadline (YYYY-MM-DD), and owner if mentioned.
- Log updates against existing commitments and infer a status \
(on_track / at_risk / missed / done) from the wording.
- Surface what's at risk, what's been completed, and what needs attention.
- Generate concise weekly summaries when asked.

Rules:
- Teams must be exactly one of: Engineering, Product, Commercial, Operations. \
If the user says "Eng" map to "Engineering"; "Sales" or "GTM" map to "Commercial"; \
"Ops" or "Finance" or "People" map to "Operations".
- Never invent commitments. If you're not sure which existing commitment a \
user's update refers to, call list_commitments first to find candidates and ask.
- Resolve relative dates ("end of month", "next Friday", "in 2 weeks") to \
absolute YYYY-MM-DD using today's date above.
- Be concise. The user is busy. Confirm actions in one short sentence.
- After taking an action, briefly state what you did and what changed.
"""


TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_commitment",
            "description": "Create a new team commitment with a deadline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "enum": db.TEAMS,
                        "description": "Which team owns this commitment.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title (max ~80 chars).",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Deadline as YYYY-MM-DD.",
                    },
                    "owner": {
                        "type": "string",
                        "description": "Person responsible for this commitment.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional longer description.",
                    },
                },
                "required": ["team", "title", "deadline"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_update",
            "description": (
                "Log a status update against an existing commitment. "
                "Will also update the commitment's status if status_inferred is provided."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "integer"},
                    "text": {"type": "string"},
                    "author": {"type": "string"},
                    "status_inferred": {
                        "type": "string",
                        "enum": db.STATUSES,
                    },
                },
                "required": ["commitment_id", "text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_status",
            "description": "Explicitly set a commitment's status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "integer"},
                    "status": {"type": "string", "enum": db.STATUSES},
                },
                "required": ["commitment_id", "status"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_deadline",
            "description": (
                "Change the deadline of an existing commitment. Use when a "
                "deadline slips and the team needs an extension. If the "
                "commitment was 'missed' and the new deadline is today or in "
                "the future, status is auto-restored to 'on_track'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "integer"},
                    "new_deadline": {
                        "type": "string",
                        "description": "New deadline as YYYY-MM-DD.",
                    },
                },
                "required": ["commitment_id", "new_deadline"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_commitments",
            "description": "List commitments. Optionally filter by team or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "enum": db.TEAMS},
                    "status": {"type": "string", "enum": db.STATUSES},
                    "include_done": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_at_risk",
            "description": (
                "Return all commitments that are currently at risk, missed, "
                "or otherwise need attention from the Founder's Associate."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_weekly_summary",
            "description": (
                "Generate a written weekly summary across all teams. "
                "Returns a markdown string."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


def _execute_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "add_commitment":
        cid = db.add_commitment(
            team=args["team"],
            title=args["title"],
            deadline=args["deadline"],
            owner=args.get("owner"),
            description=args.get("description"),
        )
        return {"ok": True, "commitment_id": cid}
    if name == "log_update":
        uid = db.log_update(
            commitment_id=args["commitment_id"],
            text=args["text"],
            author=args.get("author"),
            status_inferred=args.get("status_inferred"),
        )
        return {"ok": True, "update_id": uid}
    if name == "set_status":
        db.set_status(args["commitment_id"], args["status"])
        return {"ok": True}
    if name == "update_deadline":
        return db.update_deadline(args["commitment_id"], args["new_deadline"])
    if name == "list_commitments":
        return db.list_commitments(
            team=args.get("team"),
            status=args.get("status"),
            include_done=args.get("include_done", True),
        )
    if name == "get_at_risk":
        return db.needs_attention()
    if name == "generate_weekly_summary":
        return {"summary_markdown": generate_weekly_summary()}
    raise ValueError(f"Unknown tool: {name}")


def run_chat(messages: list[dict]) -> tuple[str, list[dict]]:
    """Run the agent loop until it produces a final assistant message.

    `messages` should already include the system prompt at index 0.
    Returns (final_text, updated_messages).
    """
    work = list(messages)
    for _ in range(8):  # hard cap on tool-use iterations
        resp = client().chat.completions.create(
            model=MODEL,
            messages=work,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message
        # Persist the assistant turn (with tool_calls if any) in the transcript
        assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        work.append(assistant_entry)

        if not msg.tool_calls:
            return msg.content or "", work

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = _execute_tool(tc.function.name, args)
            except Exception as e:  # surface tool errors back to the model
                result = {"error": str(e)}
            work.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return "(Agent stopped after too many tool iterations.)", work


def new_conversation() -> list[dict]:
    return [{"role": "system", "content": _system_prompt()}]


def generate_weekly_summary() -> str:
    """One-shot LLM call that produces a weekly exec summary across teams."""
    commitments = db.list_commitments(include_done=False)
    done_recently = [
        c for c in db.list_commitments() if c["status"] == "done"
    ]
    updates = db.recent_updates(days=7)
    attention = db.needs_attention(commitments)

    payload = {
        "today": date.today().isoformat(),
        "open_commitments": commitments,
        "completed": done_recently,
        "recent_updates_last_7_days": updates,
        "needs_attention": attention,
    }

    prompt = (
        "You are writing the weekly ops summary for LightWork AI's co-founders. "
        "Use the JSON below — do not invent facts not present.\n\n"
        "Structure the summary as markdown with these sections:\n"
        "1. **Headline** — one sentence on the overall state of the business this week.\n"
        "2. **Wins** — bullet list of completed commitments and clear positive momentum.\n"
        "3. **At risk / missed** — bullets, name the team, owner, deadline, and what's blocking.\n"
        "4. **Quiet (no recent update)** — bullets for any commitment with no update in 5+ days.\n"
        "5. **What I need from you** — 2-3 specific asks for the co-founders, only if warranted.\n\n"
        "Keep the whole thing under 300 words. Be direct, concrete, no fluff.\n\n"
        f"DATA:\n{json.dumps(payload, default=str, indent=2)}"
    )

    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You write crisp executive summaries."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def classify_update_status(commitment: dict, update_text: str) -> str | None:
    """LLM-classify a free-text update into one of the canonical statuses.

    Returns None if the model can't decide. Used by app.py when the user logs
    an update via the UI form (without going through the chat agent).
    """
    prompt = (
        f"Commitment: {commitment['team']} — {commitment['title']} "
        f"(deadline {commitment['deadline']}, currently {commitment['status']}).\n"
        f"Latest update: {update_text!r}\n\n"
        "Classify the update into exactly one of: on_track, at_risk, missed, done. "
        "Respond with just the single word, no punctuation."
    )
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a precise classifier."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=5,
    )
    raw = (resp.choices[0].message.content or "").strip().lower()
    return raw if raw in db.STATUSES else None
