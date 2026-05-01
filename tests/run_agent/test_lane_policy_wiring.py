from unittest.mock import patch

from run_agent import AIAgent


def _make_tool_defs(*names):
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _make_agent(**kwargs):
    kwargs.setdefault("api_key", "test-key-1234567890")
    with (
        patch("run_agent.get_tool_definitions", return_value=_make_tool_defs("terminal")),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("hermes_cli.config.load_config", return_value={"compression": {"enabled": False}}),
    ):
        return AIAgent(
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            **kwargs,
        )


def test_lane_stage_records_decision_without_changing_default_model():
    agent = _make_agent(
        model="existing/model",
        lane_stage="normal_turn",
        lane_node="air5",
        lane_risk="low",
    )

    assert agent.model == "existing/model"
    assert agent.lane_policy["model"] == "ministral_8b_instruct"
    assert agent.lane_policy["cache"] == "hot_session"
    assert agent.lane_policy["toolset"] == "selected"


def test_lane_model_map_can_override_concrete_model():
    agent = _make_agent(
        model="existing/model",
        lane_stage="normal_turn",
        lane_node="air5",
        lane_risk="low",
        lane_model_map={"ministral_8b_instruct": "local/ministral-8b"},
    )

    assert agent.model == "local/ministral-8b"
    assert agent.lane_policy["model"] == "ministral_8b_instruct"


def test_lane_toolset_map_applies_only_when_enabled_toolsets_absent():
    captured = {}

    def fake_get_tool_definitions(enabled_toolsets=None, disabled_toolsets=None, quiet_mode=False):
        captured["enabled_toolsets"] = enabled_toolsets
        return _make_tool_defs("terminal")

    with (
        patch("run_agent.get_tool_definitions", side_effect=fake_get_tool_definitions),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("hermes_cli.config.load_config", return_value={"compression": {"enabled": False}}),
    ):
        AIAgent(
            api_key="test-key-1234567890",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            lane_stage="diagnose",
            lane_node="imac",
            lane_risk="medium",
            lane_toolset_map={"read_only": ["file", "terminal"]},
        )

    assert captured["enabled_toolsets"] == ["file", "terminal"]


def test_explicit_enabled_toolsets_win_over_lane_toolset_map():
    captured = {}

    def fake_get_tool_definitions(enabled_toolsets=None, disabled_toolsets=None, quiet_mode=False):
        captured["enabled_toolsets"] = enabled_toolsets
        return _make_tool_defs("terminal")

    with (
        patch("run_agent.get_tool_definitions", side_effect=fake_get_tool_definitions),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("hermes_cli.config.load_config", return_value={"compression": {"enabled": False}}),
    ):
        AIAgent(
            api_key="test-key-1234567890",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            enabled_toolsets=["development"],
            lane_stage="diagnose",
            lane_node="imac",
            lane_risk="medium",
            lane_toolset_map={"read_only": ["file", "terminal"]},
        )

    assert captured["enabled_toolsets"] == ["development"]


def test_lane_maps_can_load_from_config_when_not_passed_explicitly():
    captured = {}

    def fake_get_tool_definitions(enabled_toolsets=None, disabled_toolsets=None, quiet_mode=False):
        captured["enabled_toolsets"] = enabled_toolsets
        return _make_tool_defs("terminal")

    with (
        patch("run_agent.get_tool_definitions", side_effect=fake_get_tool_definitions),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch(
            "hermes_cli.config.load_config",
            return_value={
                "compression": {"enabled": False},
                "lane_routing": {
                    "model_map": {"ministral_3b_reasoning": "local/ministral-3b-reasoning"},
                    "runtime_map": {
                        "ministral_3b_reasoning": {
                            "provider": "custom",
                            "base_url": "http://127.0.0.1:8003/v1",
                        }
                    },
                    "toolset_map": {"read_only": ["file"]},
                },
            },
        ),
    ):
        agent = AIAgent(
            model="existing/model",
            api_key="test-key-1234567890",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            lane_stage="diagnose",
            lane_node="imac",
            lane_risk="medium",
        )

    assert agent.model == "local/ministral-3b-reasoning"
    assert agent.provider == "custom"
    assert agent.base_url == "http://127.0.0.1:8003/v1"
    assert captured["enabled_toolsets"] == ["file"]


def test_lane_runtime_map_can_override_endpoint_and_model():
    agent = _make_agent(
        model="existing/model",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="original-key",
        api_mode="chat_completions",
        lane_stage="normal_turn",
        lane_node="air5",
        lane_risk="low",
        lane_runtime_map={
            "ministral_8b_instruct": {
                "model": "local/ministral-8b",
                "provider": "custom",
                "base_url": "http://127.0.0.1:8008/v1",
                "api_key": "local",
                "api_mode": "chat_completions",
            }
        },
    )

    assert agent.model == "local/ministral-8b"
    assert agent.provider == "custom"
    assert agent.base_url == "http://127.0.0.1:8008/v1"
    assert agent.api_key == "local"
    assert agent.api_mode == "chat_completions"


def test_lane_model_map_wins_over_runtime_map_model():
    agent = _make_agent(
        model="existing/model",
        lane_stage="normal_turn",
        lane_node="air5",
        lane_risk="low",
        lane_runtime_map={
            "ministral_8b_instruct": {
                "model": "runtime/model",
                "base_url": "http://127.0.0.1:8008/v1",
            }
        },
        lane_model_map={"ministral_8b_instruct": "model-map/model"},
    )

    assert agent.model == "model-map/model"
    assert agent.base_url == "http://127.0.0.1:8008/v1"


def test_rust_lane_policy_can_drive_lane_maps_when_enabled():
    rust_payload = {
        "bridge_mode": "preview-only",
        "decision": {
            "lane": "reasoning",
            "model": "ministral_8b_reasoning",
            "target_node": "air5",
            "cache": "expanded",
            "toolset": "repo_read_only",
            "persona": "none",
            "runtime_first": False,
            "escalate": True,
        },
    }

    with (
        patch.dict("os.environ", {"HERMES_RUST_LANE_POLICY": "1"}, clear=False),
        patch("run_agent._request_rust_lane_policy", return_value=rust_payload) as request_policy,
    ):
        agent = _make_agent(
            model="existing/model",
            lane_stage="complex_plan",
            lane_node="air1",
            lane_risk="high",
            lane_runtime_map={
                "ministral_8b_reasoning": {
                    "model": "local/devstral-reasoning",
                    "provider": "custom",
                    "base_url": "http://127.0.0.1:8009/v1",
                }
            },
            lane_toolset_map={"repo_read_only": ["file", "terminal"]},
        )

    request_policy.assert_called_once()
    assert agent.lane_policy_source == "rust"
    assert agent.lane_policy["model"] == "ministral_8b_reasoning"
    assert agent.model == "local/devstral-reasoning"
    assert agent.provider == "custom"
    assert agent.base_url == "http://127.0.0.1:8009/v1"


def test_rust_lane_policy_failure_falls_back_to_python_policy():
    with (
        patch.dict("os.environ", {"HERMES_RUST_LANE_POLICY": "1"}, clear=False),
        patch("run_agent._request_rust_lane_policy", side_effect=TimeoutError("offline")),
    ):
        agent = _make_agent(
            model="existing/model",
            lane_stage="diagnose",
            lane_node="imac",
            lane_risk="medium",
        )

    assert agent.lane_policy_source == "python"
    assert agent.lane_policy["model"] == "ministral_3b_reasoning"
    assert agent._last_rust_lane_policy["applied"] is False
