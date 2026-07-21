"""The default-profile fallback is silent and lands on someone else's bill.

These tests exist because the failure is invisible: boto3 quietly picks
[default] from ~/.aws/credentials, everything works, and the wrong account
gets charged under the wrong identity. Only a hard error surfaces it.
"""

import importlib

import pytest

import src.config as config


@pytest.fixture
def cfg(monkeypatch):
    """Reload config with a clean environment each time."""

    def _load(**env):
        for var in (
            "AWS_PROFILE",
            "AWS_ACCESS_KEY_ID",
            "AWS_ALLOW_DEFAULT_PROFILE",
            "AWS_LAMBDA_FUNCTION_NAME",
            "AWS_EXECUTION_ENV",
            "ECS_CONTAINER_METADATA_URI",
            "ECS_CONTAINER_METADATA_URI_V4",
        ):
            monkeypatch.delenv(var, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _load
    importlib.reload(config)


def test_refuses_to_guess_when_no_profile_is_set(cfg):
    mod = cfg()
    with pytest.raises(RuntimeError, match="AWS_PROFILE is not set"):
        mod.aws_session()


def test_the_error_tells_you_how_to_fix_it(cfg):
    mod = cfg()
    with pytest.raises(RuntimeError) as err:
        mod.aws_session()
    message = str(err.value)
    assert "aws configure --profile personal" in message
    assert "get-caller-identity" in message


def test_named_profile_is_used(cfg):
    mod = cfg(AWS_PROFILE="personal")
    assert mod.AWS_PROFILE == "personal"


def test_lambda_may_use_its_execution_role(cfg):
    """No credentials file in Lambda, so there is nothing ambiguous to guard."""
    mod = cfg(AWS_LAMBDA_FUNCTION_NAME="incident-copilot")
    assert mod.aws_session() is not None


def test_ecs_may_use_its_task_role(cfg):
    mod = cfg(ECS_CONTAINER_METADATA_URI_V4="http://169.254.170.2/v4/abc")
    assert mod.aws_session() is not None


def test_explicit_env_credentials_are_accepted(cfg):
    """CI supplies keys directly; that is a deliberate choice, not a fallback."""
    mod = cfg(AWS_ACCESS_KEY_ID="AKIAEXAMPLE")
    assert mod.aws_session() is not None


def test_opt_out_is_available_but_must_be_deliberate(cfg):
    mod = cfg(AWS_ALLOW_DEFAULT_PROFILE="1")
    assert mod.aws_session() is not None
