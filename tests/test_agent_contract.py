"""The agent's tool surface is a contract with the model. If a tool name or a
required field drifts, the model silently stops being able to reach memory --
so it is worth asserting on."""

from src import agent

TOOL_NAMES = {t["name"] for t in agent.TOOLS}


def test_the_three_memory_tools_are_exposed():
    assert TOOL_NAMES == {
        "recall_similar_incidents",
        "recall_lessons",
        "record_finding",
    }


def test_every_tool_has_a_well_formed_schema():
    for tool in agent.TOOLS:
        assert tool["description"].strip()
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        for field in schema["required"]:
            assert field in schema["properties"], f"{tool['name']}: {field}"


def test_record_finding_requires_what_memory_needs():
    """These three are NOT NULL in the incidents table."""
    schema = next(t for t in agent.TOOLS if t["name"] == "record_finding")
    assert set(schema["input_schema"]["required"]) >= {
        "title",
        "service",
        "symptoms",
    }


def test_system_prompt_forbids_stretching_a_weak_match():
    """A confident wrong recall is worse than admitting no recall."""
    assert "SAY SO" in agent.SYSTEM_PROMPT
    assert "recall" in agent.SYSTEM_PROMPT.lower()


def test_unknown_tool_does_not_raise():
    """The model occasionally hallucinates a tool name; we must return a
    result block rather than blow up the whole session."""
    assert "Unknown tool" in agent._run_tool("nope", {}, "session-id")
