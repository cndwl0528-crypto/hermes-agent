import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource


class _CapturingAgent:
    last_init = None

    def __init__(self, *args, **kwargs):
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(self, *args, **kwargs):
        return {"final_response": "ok", "messages": [], "api_calls": 1, "completed": True}


def _install_fake_agent(monkeypatch):
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)


def _make_runner():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._service_tier = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._smart_model_routing = {}
    runner._running_agents = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(streaming=None)
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda source: SimpleNamespace(session_id="session-1"),
        load_transcript=lambda session_id: [],
    )
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._enrich_message_with_vision = AsyncMock(return_value="hi")
    return runner


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="12345",
        chat_type="dm",
        user_id="user-1",
    )


@pytest.mark.asyncio
async def test_gateway_agent_receives_lane_kwargs(monkeypatch):
    _install_fake_agent(monkeypatch)
    runner = _make_runner()
    config = {
        "lane_routing": {
            "entrypoints": {"gateway": {"node": "imac", "risk": "medium"}},
            "model_map": {"ministral_3b_instruct": "local/3b"},
            "runtime_map": {
                "ministral_3b_instruct": {
                    "provider": "custom",
                    "base_url": "http://127.0.0.1:8003/v1",
                }
            },
            "toolset_map": {"selected": ["file"]},
        },
    }
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: config)
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "base/model")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
        },
    )

    import hermes_cli.tools_config as tools_config
    monkeypatch.setattr(tools_config, "_get_platform_tools", lambda user_config, platform_key: {"core"})

    result = await runner._run_agent(
        message="hi",
        context_prompt="",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:telegram:dm:12345",
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["lane_stage"] == "normal_turn"
    assert _CapturingAgent.last_init["lane_node"] == "imac"
    assert _CapturingAgent.last_init["lane_risk"] == "medium"
    assert _CapturingAgent.last_init["lane_model_map"] == {"ministral_3b_instruct": "local/3b"}
    assert _CapturingAgent.last_init["lane_runtime_map"] == {
        "ministral_3b_instruct": {
            "provider": "custom",
            "base_url": "http://127.0.0.1:8003/v1",
        }
    }
    assert _CapturingAgent.last_init["lane_toolset_map"] == {"selected": ["file"]}
    assert _CapturingAgent.last_init["enabled_toolsets"] is None


def test_agent_cache_signature_includes_lane_kwargs():
    runtime = {"api_key": "test-key", "base_url": "http://local", "provider": "custom"}
    base = gateway_run.GatewayRunner._agent_config_signature(
        "model",
        runtime,
        ["core"],
        "",
        {"lane_stage": "normal_turn", "lane_node": "air5"},
    )
    changed = gateway_run.GatewayRunner._agent_config_signature(
        "model",
        runtime,
        ["core"],
        "",
        {"lane_stage": "diagnose", "lane_node": "air5"},
    )

    assert base != changed


@pytest.mark.asyncio
async def test_session_model_override_suppresses_lane_model_map(monkeypatch):
    _install_fake_agent(monkeypatch)
    runner = _make_runner()
    runner._session_model_overrides["agent:main:telegram:dm:12345"] = {"model": "manual/model"}
    config = {
        "lane_routing": {
            "model_map": {"ministral_8b_instruct": "local/8b"},
            "runtime_map": {
                "ministral_8b_instruct": {
                    "base_url": "http://127.0.0.1:8008/v1",
                }
            },
        }
    }
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: config)
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "base/model")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
        },
    )

    import hermes_cli.tools_config as tools_config
    monkeypatch.setattr(tools_config, "_get_platform_tools", lambda user_config, platform_key: {"core"})

    await runner._run_agent(
        message="hi",
        context_prompt="",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:telegram:dm:12345",
    )

    assert _CapturingAgent.last_init["model"] == "manual/model"
    assert _CapturingAgent.last_init["lane_model_map"] == {}
    assert _CapturingAgent.last_init["lane_runtime_map"] == {}
