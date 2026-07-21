"""The agent loop: recall -> reason -> act -> write back.

Claude runs on Amazon Bedrock and is given tools that read and write
CockroachDB memory. The important property is the last step: every run
*deposits* something durable, so the next run starts smarter than this one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import boto3

from . import config, memory

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


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def _invoke(messages: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "system": SYSTEM_PROMPT,
            "tools": TOOLS,
            "messages": messages,
        }
    )
    resp = _client().invoke_model(modelId=config.CHAT_MODEL_ID, body=body)
    return json.loads(resp["body"].read())


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
            f"- {l.statement}  (confidence {l.confidence:.2f})" for l in lessons
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

    messages: list[dict[str, Any]] = [{"role": "user", "content": alert_text}]
    tools_used: list[str] = []

    for _ in range(max_turns):
        reply = _invoke(messages)
        messages.append({"role": "assistant", "content": reply["content"]})

        for block in reply["content"]:
            if block["type"] == "text" and block["text"].strip():
                memory.append_step(session_id, "assistant", block["text"])

        if reply.get("stop_reason") != "tool_use":
            break

        results = []
        for block in reply["content"]:
            if block["type"] != "tool_use":
                continue
            tools_used.append(block["name"])
            output = _run_tool(block["name"], block["input"], session_id)
            memory.append_step(
                session_id, "memory", f"{block['name']} -> {output[:2000]}"
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": output,
                }
            )
        messages.append({"role": "user", "content": results})

    memory.close_session(session_id)

    answer = "\n".join(
        b["text"] for b in messages[-1]["content"]
        if isinstance(b, dict) and b.get("type") == "text"
    ) if isinstance(messages[-1]["content"], list) else ""

    return {"session_id": session_id, "answer": answer, "tools_used": tools_used}
