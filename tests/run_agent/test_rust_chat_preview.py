import json

from run_agent import (
    DEFAULT_RUST_CHAT_PREVIEW_URL,
    AIAgent,
    _build_rust_chat_preview_payload,
    _request_rust_chat_preview,
    _rust_chat_preview_enabled,
    _rust_chat_preview_result_text,
)


def test_rust_chat_preview_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PREVIEW", raising=False)
    monkeypatch.delenv("HERMES_RUST_CHAT_PRIMARY", raising=False)

    assert _rust_chat_preview_enabled() is False


def test_rust_chat_primary_enables_plain_chat_rust_path(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PREVIEW", raising=False)
    monkeypatch.setenv("HERMES_RUST_CHAT_PRIMARY", "1")

    assert _rust_chat_preview_enabled() is True


def test_rust_chat_preview_flag_remains_compatibility_alias(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PRIMARY", raising=False)
    monkeypatch.setenv("HERMES_RUST_CHAT_PREVIEW", "1")

    assert _rust_chat_preview_enabled() is True


def test_build_rust_chat_preview_payload_preserves_plain_messages():
    payload = _build_rust_chat_preview_payload(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": {"answer": "old"}},
            {"role": "user", "content": "next"},
        ],
        session_id="session-a",
        max_new_tokens=64,
    )

    assert payload["session_id"] == "session-a"
    assert payload["mode"] == "chat"
    assert payload["stream"] is False
    assert payload["fallback_allowed"] is True
    assert payload["max_new_tokens"] == 64
    assert payload["messages"][0] == {"role": "system", "content": "system rules"}
    assert payload["messages"][2]["role"] == "assistant"
    assert '"answer": "old"' in payload["messages"][2]["content"]


def test_request_rust_chat_preview_posts_expected_json():
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "used_runtime": "rust",
                "fallback_reason": None,
                "text": "hello from rust",
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    response = _request_rust_chat_preview(
        DEFAULT_RUST_CHAT_PREVIEW_URL,
        {"session_id": "session-a", "messages": [{"role": "user", "content": "hi"}]},
        timeout=0.25,
        urlopen=fake_urlopen,
    )

    assert response["text"] == "hello from rust"
    request, timeout = calls[0]
    assert timeout == 0.25
    assert request.full_url == DEFAULT_RUST_CHAT_PREVIEW_URL
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8"))["session_id"] == "session-a"


def test_rust_chat_preview_result_text_requires_rust_runtime():
    assert _rust_chat_preview_result_text({
        "used_runtime": "rust",
        "fallback_reason": None,
        "text": " ok ",
    }) == "ok"
    assert _rust_chat_preview_result_text({
        "used_runtime": "python_fallback",
        "fallback_reason": "unsupported_mode",
        "text": "fallback",
    }) is None
    assert _rust_chat_preview_result_text({
        "used_runtime": "rust",
        "fallback_reason": "worker_error",
        "text": "fallback",
    }) is None


def test_maybe_rust_chat_preview_response_applies_when_enabled(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PREVIEW", raising=False)
    monkeypatch.setenv("HERMES_RUST_CHAT_PRIMARY", "1")

    def fake_request(url, payload, *, timeout):
        assert payload["session_id"] == "test-session"
        assert payload["messages"][-1] == {"role": "user", "content": "route this"}
        return {
            "used_runtime": "rust",
            "fallback_reason": None,
            "text": "routed by rust",
        }

    monkeypatch.setattr("run_agent._request_rust_chat_preview", fake_request)

    agent = object.__new__(AIAgent)
    agent.session_id = "test-session"
    agent.max_tokens = 128
    agent.tools = []
    agent.quiet_mode = True
    agent.verbose_logging = False
    agent.log_prefix = ""

    text = agent._maybe_rust_chat_preview_response([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "route this"},
    ])

    assert text == "routed by rust"
    assert agent._last_rust_chat_preview["used_runtime"] == "rust"


def test_maybe_rust_chat_preview_response_skips_tool_turns(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PREVIEW", raising=False)
    monkeypatch.setenv("HERMES_RUST_CHAT_PRIMARY", "1")

    agent = object.__new__(AIAgent)
    agent.tools = [{"type": "function"}]

    text = agent._maybe_rust_chat_preview_response([
        {"role": "user", "content": "needs a tool"},
    ])

    assert text is None
    assert agent._last_rust_chat_preview == {
        "applied": False,
        "reason": "tools_or_transcript_present",
    }


def test_maybe_rust_chat_preview_response_falls_back_when_rust_unavailable(monkeypatch):
    monkeypatch.delenv("HERMES_RUST_CHAT_PREVIEW", raising=False)
    monkeypatch.setenv("HERMES_RUST_CHAT_PRIMARY", "1")

    def fake_request(url, payload, *, timeout):
        raise TimeoutError("rust bridge unavailable")

    monkeypatch.setattr("run_agent._request_rust_chat_preview", fake_request)

    agent = object.__new__(AIAgent)
    agent.session_id = "test-session"
    agent.max_tokens = 128
    agent.tools = []
    agent.quiet_mode = True
    agent.verbose_logging = False
    agent.log_prefix = ""

    text = agent._maybe_rust_chat_preview_response([
        {"role": "user", "content": "continue on python"},
    ])

    assert text is None
    assert agent._last_rust_chat_preview["applied"] is False
    assert "rust bridge unavailable" in agent._last_rust_chat_preview["error"]
