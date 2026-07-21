"""Route-level tests with memory and Bedrock stubbed out."""

import json

import pytest

from src import lambda_handler


@pytest.fixture(autouse=True)
def stub_backends(monkeypatch):
    monkeypatch.setattr(
        lambda_handler.memory,
        "stats",
        lambda: {"incidents": 8, "lessons": 8, "sessions": 0, "recalls": 0},
    )
    monkeypatch.setattr(
        lambda_handler.memory,
        "get_session",
        lambda sid: {"id": sid, "steps": []} if sid == "known" else None,
    )
    monkeypatch.setattr(
        lambda_handler.agent,
        "handle_alert",
        lambda alert, service=None: {
            "session_id": "s1",
            "answer": "matches INC-1041",
            "tools_used": ["recall_similar_incidents"],
        },
    )


def _event(path, method="GET", body=None, query=None):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(body) if body else None,
        "queryStringParameters": query,
    }


def _body(response):
    return json.loads(response["body"])


def test_stats_route():
    res = lambda_handler.handler(_event("/stats"), None)
    assert res["statusCode"] == 200
    assert _body(res)["incidents"] == 8


def test_alert_route_runs_the_agent():
    res = lambda_handler.handler(
        _event("/alert", "POST", {"alert": "p99 spiking, CPU flat"}), None
    )
    assert res["statusCode"] == 200
    assert _body(res)["answer"] == "matches INC-1041"


def test_alert_route_rejects_empty_body():
    res = lambda_handler.handler(_event("/alert", "POST", {}), None)
    assert res["statusCode"] == 400


def test_session_route_requires_an_id():
    assert lambda_handler.handler(_event("/session"), None)["statusCode"] == 400


def test_session_route_404s_on_unknown_id():
    res = lambda_handler.handler(_event("/session", query={"id": "nope"}), None)
    assert res["statusCode"] == 404


def test_session_route_returns_the_trace():
    res = lambda_handler.handler(_event("/session", query={"id": "known"}), None)
    assert res["statusCode"] == 200
    assert _body(res)["id"] == "known"


def test_unknown_route_404s():
    assert lambda_handler.handler(_event("/nope"), None)["statusCode"] == 404


def test_cors_header_is_present_so_the_ui_can_call_it():
    res = lambda_handler.handler(_event("/stats"), None)
    assert res["headers"]["Access-Control-Allow-Origin"] == "*"


def test_failures_surface_as_500_not_a_crash(monkeypatch):
    def boom():
        raise RuntimeError("cluster unreachable")

    monkeypatch.setattr(lambda_handler.memory, "stats", boom)
    res = lambda_handler.handler(_event("/stats"), None)
    assert res["statusCode"] == 500
    assert _body(res)["error"] == "RuntimeError"
