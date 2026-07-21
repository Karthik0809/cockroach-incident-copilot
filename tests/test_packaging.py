"""Guardrails for things that only fail at deploy time.

These exist because the failure mode is expensive: you find out at `sam deploy`,
after a long build, with an error that does not name the actual cause.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Streamlit pulls pyarrow + pandas + numpy + altair + pydeck + PIL, roughly
# 260MB unzipped -- past Lambda's 250MB limit on its own.
UI_ONLY = {"streamlit", "pandas", "pyarrow", "numpy", "altair", "pydeck", "pillow"}


def _packages(path: pathlib.Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r ", "-e ")):
            continue
        names.add(
            line.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower()
        )
    return names


def test_lambda_requirements_exclude_ui_dependencies():
    """requirements.txt is what SAM packages into the Lambda."""
    assert not (_packages(ROOT / "requirements.txt") & UI_ONLY)


def test_ui_requirements_include_streamlit():
    assert "streamlit" in _packages(ROOT / "requirements-ui.txt")


def test_ui_requirements_inherit_the_core_set():
    """So the UI never drifts to a different psycopg or boto3 than the agent."""
    assert "-r requirements.txt" in (ROOT / "requirements-ui.txt").read_text(
        encoding="utf-8"
    )


def test_lambda_still_has_what_it_actually_imports():
    core = _packages(ROOT / "requirements.txt")
    assert {"psycopg", "boto3", "python-dotenv"} <= core


def test_dockerfile_installs_the_ui_requirements():
    assert "requirements-ui.txt" in (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_schema_statements_split_cleanly():
    """init_schema applies the DDL statement by statement. Every fragment the
    splitter produces must be a real statement -- this caught a semicolon
    inside a SQL comment that severed a CREATE TABLE in half."""
    from src.memory import split_statements

    sql = (ROOT / "schema" / "001_schema.sql").read_text(encoding="utf-8")
    statements = split_statements(sql)

    assert len(statements) >= 8
    for statement in statements:
        assert statement.upper().startswith(("CREATE", "SET")), statement[:60]


def test_splitter_survives_a_semicolon_inside_a_comment():
    from src.memory import split_statements

    script = """
    -- a note; with a semicolon in it
    CREATE TABLE a (id INT);
    CREATE TABLE b (id INT);  -- trailing; comment
    """
    assert len(split_statements(script)) == 2


def test_splitter_drops_comment_only_input():
    from src.memory import split_statements

    assert split_statements("-- nothing here\n-- still nothing\n") == []
