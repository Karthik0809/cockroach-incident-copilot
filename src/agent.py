"""The agent loop: recall -> reason -> act -> write back.

Runs on Amazon Bedrock through the **Converse API**, which is deliberately
model-agnostic: the same tool definitions and the same loop drive Claude, Nova,
or anything else Bedrock exposes, selected by CHAT_MODEL_ID alone. That matters
operationally -- Anthropic models on Bedrock require an AWS Marketplace
subscription while Amazon's first-party models do not, so an account issue on
one family should never be a code change.

The important property of the loop is its last step: every run *deposits*
something durable, so the next run starts smarter than this one.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import boto3

from . import config, memory

# Some Bedrock models (Nova especially) narrate their planning inside
# <thinking> tags in the visible text. Useful to log, noise to an on-call
# engineer, so it is stripped from the answer but kept in the session trace.
_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    return _THINKING.sub("", text).strip()


SYSTEM_PROMPT = """You are Incident Copilot, an on-call engineering agent.

You have persistent memory of every incident this organization has ever handled.
Before you theorize, you recall. Your value is not general reasoning -- it is
knowing what THIS team saw last time.

Process:
1. Call recall_similar_incidents with the alert text. Always. Even if the alert
   looks obvious.
2. Call recall_lessons for accumulated guidance.
3. If a past incident genuinely matches, say so explicitly and cite its date and
   title. Ground your recommendation in what actually fixed it before.
4. If nothing in memory matches, SAY SO plainly. Do not stretch a weak match
   into a false precedent -- a confident wrong recall is worse than no recall.
5. Finish by calling record_finding exactly once to write what you concluded
   back into memory.

Be concise. On-call engineers are reading you at 3am."""

# Converse-API tool specs. One definition, every model family.
TOOLS = [
    {
        "name": "recall_similar_incidents",
        "description": (
            "Semantic search over every past incident, using CockroachDB's "
            "distributed vector index. Returns the closest matches with a "
            "similarity score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symptom description to search memory with.",
                },
                "service": {
                    "type": "string",
                    "description": "Optional: restrict to one service.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall_lessons",
        "description": (
            "Retrieve durable lessons the team has learned, ranked by semantic "
            "match and by how often the lesson has held up in practice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "record_finding",
        "description": (
            "Write this incident and its diagnosis back into long-term memory. "
            "Call this exactly once, at the end."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "service": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["SEV1", "SEV2", "SEV3", "SEV4"],
                },
                "symptoms": {"type": "string"},
                "root_cause": {"type": "string"},
                "resolution": {"type": "string"},
                "lesson": {
                    "type": "string",
                    "description": (
                        "One generalizable sentence worth remembering beyond "
                        "this specific incident."
                    ),
                },
            },
            "required": ["title", "service", "symptoms"],
        },
    },
]


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": {"json": t["input_schema"]},
                }
            }
            for t in TOOLS
        ]
    }


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def _converse(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return _client().converse(
        modelId=config.CHAT_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=messages,
        toolConfig=_tool_config(),
        inferenceConfig={"maxTokens": 2048, "temperature": 0.2},
    )


def _run_tool(name: str, args: dict[str, Any], session_id: str) -> str:
    if name == "recall_similar_incidents":
        hits = memory.recall_incidents(args["query"], service=args.get("service"))
        for hit in hits:
            memory.log_recall(
                session_id, similarity=hit.similarity, incident_id=hit.incident_id
            )
        if not hits:
            return "NO MATCH. Memory contains nothing similar to this alert."
        return "\n\n".join(h.as_prompt_block() for h in hits)

    if name == "recall_lessons":
        lessons = memory.recall_lessons(args["query"])
        for lesson in lessons:
            memory.log_recall(
                session_id,
                similarity=1.0 - lesson.distance,
                lesson_id=lesson.lesson_id,
            )
        if not lessons:
            return "No lessons recorded yet."
        return "\n".join(
            f"- {x.statement}  (confidence {x.confidence:.2f})" for x in lessons
        )

    if name == "record_finding":
        incident_id = memory.remember_incident(
            title=args["title"],
            service=args["service"],
            symptoms=args["symptoms"],
            severity=args.get("severity", "SEV3"),
            root_cause=args.get("root_cause"),
            resolution=args.get("resolution"),
        )
        if args.get("lesson"):
            memory.remember_lesson(incident_id, args["lesson"])
        return f"Committed to memory as incident {incident_id}."

    return f"Unknown tool: {name}"


def handle_alert(
    alert_text: str, service: str | None = None, max_turns: int = 6
) -> dict[str, Any]:
    """Run one full incident. Returns the answer plus the session id, so the
    caller can replay the exact reasoning later from the database."""
    session_id = memory.open_session(alert_text, service)
    memory.append_step(session_id, "user", alert_text)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": alert_text}]}
    ]
    tools_used: list[str] = []
    said: list[str] = []
    finished = False

    for _ in range(max_turns):
        reply = _converse(messages)
        content = reply["output"]["message"]["content"]
        messages.append({"role": "assistant", "content": content})

        for block in content:
            if "text" in block and block["text"].strip():
                # Full text (planning included) goes to the durable trace;
                # only the cleaned version is surfaced as the answer.
                memory.append_step(session_id, "assistant", block["text"])
                visible = strip_thinking(block["text"])
                if visible:
                    said.append(visible)

        if reply.get("stopReason") != "tool_use":
            finished = True
            break

        results = []
        for block in content:
            if "toolUse" not in block:
                continue
            use = block["toolUse"]
            tools_used.append(use["name"])
            output = _run_tool(use["name"], use["input"], session_id)
            memory.append_step(
                session_id, "memory", f"{use['name']} -> {output[:2000]}"
            )
            results.append(
                {
                    "toolResult": {
                        "toolUseId": use["toolUseId"],
                        "content": [{"text": output}],
                    }
                }
            )
        messages.append({"role": "user", "content": results})

    # Accumulate text as it arrives rather than reading it off the last
    # message: when max_turns runs out, the last message is a toolResult,
    # and reading that back would silently return an empty answer.
    memory.close_session(session_id, "resolved" if finished else "truncated")

    return {
        "session_id": session_id,
        "answer": "\n\n".join(said),
        "tools_used": tools_used,
        "truncated": not finished,
        "model": config.CHAT_MODEL_ID,
    }
