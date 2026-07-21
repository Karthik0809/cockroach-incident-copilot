"""AWS Lambda entry point (behind a Function URL or API Gateway).

Routes:
  POST /alert       {"alert": "...", "service": "..."}  -> run the agent
  GET  /session     ?id=<uuid>                          -> replay memory
  GET  /stats                                           -> memory counters
"""

import json
from typing import Any

from . import agent, memory


def _response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    path = event.get("rawPath") or event.get("path") or "/"
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "GET"
    )

    try:
        if path.endswith("/stats"):
            return _response(200, memory.stats())

        if path.endswith("/session"):
            session_id = (event.get("queryStringParameters") or {}).get("id")
            if not session_id:
                return _response(400, {"error": "missing ?id="})
            found = memory.get_session(session_id)
            if not found:
                return _response(404, {"error": "no such session"})
            return _response(200, found)

        if path.endswith("/alert") and method == "POST":
            body = json.loads(event.get("body") or "{}")
            alert = body.get("alert")
            if not alert:
                return _response(400, {"error": "missing 'alert'"})
            return _response(200, agent.handle_alert(alert, body.get("service")))

        return _response(404, {"error": f"no route for {method} {path}"})

    except Exception as exc:  # surface the real error; this is a demo service
        return _response(500, {"error": type(exc).__name__, "detail": str(exc)})
