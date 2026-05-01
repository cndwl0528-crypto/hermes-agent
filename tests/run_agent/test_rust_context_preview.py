import json

from run_agent import (
    DEFAULT_RUST_CONTEXT_PREVIEW_URL,
    DEFAULT_RUST_RUNTIME_CONTRACT_URL,
    AIAgent,
    _apply_rust_context_preview_packet,
    _build_rust_context_preview_payload,
    _request_rust_context_preview,
    _request_rust_runtime_contract,
    _rust_context_apply_enabled,
    _rust_context_preview_enabled,
    _rust_runtime_contract_enabled,
)


def test_rust_context_preview_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PREVIEW", raising=False)
    monkeypatch.delenv("HERMES_RUST_CONTEXT_APPLY", raising=False)

    assert _rust_context_preview_enabled() is False
    assert _rust_context_apply_enabled() is False
    assert _rust_runtime_contract_enabled() is False


def test_rust_context_primary_enables_preview_and_apply(monkeypatch):
    monkeypatch.setenv("HERMES_RUST_CONTEXT_PRIMARY", "1")
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PREVIEW", raising=False)
    monkeypatch.delenv("HERMES_RUST_CONTEXT_APPLY", raising=False)

    assert _rust_context_preview_enabled() is True
    assert _rust_context_apply_enabled() is True


def test_rust_context_preview_flag_remains_dry_run_alias(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PRIMARY", raising=False)
    monkeypatch.setenv("HERMES_RUST_CONTEXT_PREVIEW", "1")
    monkeypatch.delenv("HERMES_RUST_CONTEXT_APPLY", raising=False)

    assert _rust_context_preview_enabled() is True
    assert _rust_context_apply_enabled() is False


def test_rust_context_apply_flag_does_not_request_preview_by_itself(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PREVIEW", raising=False)
    monkeypatch.setenv("HERMES_RUST_CONTEXT_APPLY", "1")

    assert _rust_context_preview_enabled() is False
    assert _rust_context_apply_enabled() is True


def test_build_rust_context_preview_payload_preserves_message_content():
    payload = _build_rust_context_preview_payload(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "old request"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current request"},
        ],
        max_prompt_tokens=100,
        reserved_response_tokens=16,
    )

    assert payload["budget"] == {
        "max_prompt_tokens": 100,
        "reserved_response_tokens": 16,
    }
    assert payload["segments"][0]["id"] == "0:system"
    assert payload["segments"][0]["required"] is True
    assert payload["segments"][0]["priority"] == 255
    assert payload["segments"][1]["required"] is False
    assert payload["segments"][3]["id"] == "3:user"
    assert payload["segments"][3]["required"] is True
    assert payload["segments"][3]["priority"] == 240
    assert payload["segments"][3]["content"] == "current request"


def test_request_rust_context_preview_posts_expected_json():
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "bridge_mode": "preview-only",
                "packet": {"selected": [], "dropped": [], "pressure": "normal"},
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    response = _request_rust_context_preview(
        DEFAULT_RUST_CONTEXT_PREVIEW_URL,
        {"budget": {"max_prompt_tokens": 10, "reserved_response_tokens": 2}, "segments": []},
        timeout=0.25,
        urlopen=fake_urlopen,
    )

    assert response["bridge_mode"] == "preview-only"
    request, timeout = calls[0]
    assert timeout == 0.25
    assert request.full_url == DEFAULT_RUST_CONTEXT_PREVIEW_URL
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8"))["budget"]["max_prompt_tokens"] == 10


def test_request_rust_runtime_contract_posts_session_id():
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "bridge_mode": "preview-only",
                "system_message": "Runtime compatibility contract",
                "contract": {"contract_version": "hermes_mac_code_candle_devstral_v1"},
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    response = _request_rust_runtime_contract(
        DEFAULT_RUST_RUNTIME_CONTRACT_URL,
        session_id="session-a",
        timeout=0.2,
        urlopen=fake_urlopen,
    )

    assert response["system_message"] == "Runtime compatibility contract"
    request, timeout = calls[0]
    assert timeout == 0.2
    assert request.full_url == DEFAULT_RUST_RUNTIME_CONTRACT_URL
    assert json.loads(request.data.decode("utf-8"))["session_id"] == "session-a"


def test_apply_rust_context_preview_packet_keeps_selected_messages_in_order():
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current request"},
    ]
    preview = {
        "packet": {
            "selected": [
                {"id": "0:system"},
                {"id": "3:user"},
            ],
            "dropped": [{"id": "1:user"}, {"id": "2:assistant"}],
            "pressure": "tight",
        }
    }

    packed, result = _apply_rust_context_preview_packet(messages, preview)

    assert result == {
        "applied": True,
        "selected": 2,
        "dropped": 2,
        "pressure": "tight",
    }
    assert [message["content"] for message in packed] == ["system rules", "current request"]
    assert messages[1]["content"] == "old request"


def test_apply_rust_context_preview_packet_skips_tool_transcripts():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "result"},
    ]
    preview = {"packet": {"selected": [{"id": "1:tool"}], "pressure": "normal"}}

    packed, result = _apply_rust_context_preview_packet(messages, preview)

    assert packed is messages
    assert result == {"applied": False, "reason": "tool_transcript_present"}


def test_maybe_preview_rust_context_budget_applies_when_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_RUST_CONTEXT_PRIMARY", "1")
    monkeypatch.delenv("HERMES_RUST_CONTEXT_PREVIEW", raising=False)
    monkeypatch.delenv("HERMES_RUST_CONTEXT_APPLY", raising=False)
    monkeypatch.setenv("HERMES_RUST_CONTEXT_PREVIEW_MAX_PROMPT_TOKENS", "100")
    monkeypatch.setenv("HERMES_RUST_CONTEXT_PREVIEW_RESERVED_RESPONSE_TOKENS", "16")

    def fake_request(url, payload, *, timeout):
        assert payload["segments"][0]["id"] == "0:system"
        return {
            "bridge_mode": "preview-only",
            "packet": {
                "selected": [
                    {"id": "0:system"},
                    {"id": "2:user"},
                ],
                "dropped": [{"id": "1:assistant"}],
                "pressure": "tight",
            },
        }

    monkeypatch.setattr("run_agent._request_rust_context_preview", fake_request)

    agent = object.__new__(AIAgent)
    agent.session_id = "test"
    agent.context_compressor = None
    agent.max_tokens = None
    agent.quiet_mode = True
    agent.verbose_logging = False
    agent.log_prefix = ""

    packed = agent._maybe_preview_rust_context_budget(
        [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "old"},
            {"role": "user", "content": "current"},
        ],
        10,
    )

    assert [message["content"] for message in packed] == ["system", "current"]
    assert agent._last_rust_context_apply["applied"] is True


def test_maybe_rust_runtime_contract_system_message_applies_when_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_RUST_RUNTIME_CONTRACT", "1")

    def fake_request(url, *, session_id, timeout):
        assert session_id == "test-session"
        return {
            "bridge_mode": "preview-only",
            "system_message": "Hermes owns user memory; Candle owns Rust/Metal execution.",
        }

    monkeypatch.setattr("run_agent._request_rust_runtime_contract", fake_request)

    agent = object.__new__(AIAgent)
    agent.session_id = "test-session"
    agent.quiet_mode = True
    agent.verbose_logging = False
    agent.log_prefix = ""

    message = agent._maybe_rust_runtime_contract_system_message()

    assert "Hermes owns user memory" in message
    assert agent._last_rust_runtime_contract["bridge_mode"] == "preview-only"
