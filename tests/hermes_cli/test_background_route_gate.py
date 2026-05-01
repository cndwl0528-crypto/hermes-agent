import json
from unittest.mock import patch

from cli import HermesCLI
from hermes_cli.route_gate import (
    deterministic_hermes_route_gate,
    deterministic_hermes_route_dispatch_packet,
    deterministic_hermes_route_gate_text,
    route_dispatch_primary_enabled,
)


def test_route_dispatch_primary_defaults_on(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    assert route_dispatch_primary_enabled() is True


def test_route_dispatch_primary_env_can_disable_gate(monkeypatch):
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_PRIMARY", "0")
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    assert route_dispatch_primary_enabled() is False
    assert deterministic_hermes_route_gate(
        "Task: inspect a 24B safetensors coding model. Options: self, air5, specialist."
    ) is None


def test_route_dispatch_disabled_env_overrides_primary(monkeypatch):
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_PRIMARY", "1")
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_DISABLED", "1")

    assert route_dispatch_primary_enabled() is False


def test_deterministic_route_gate_maps_24b_conversion_to_specialist(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    decision = deterministic_hermes_route_gate(
        "Task: inspect a 24B safetensors coding model and design a conversion runner. "
        "Options: self, air5, specialist."
    )

    assert decision == {
        "reason": "inspect a 24B safetensors coding model and design a conversion runner.",
        "route": "specialist",
        "source": "deterministic_gate",
        "escalation": "l2_mario",
    }


def test_deterministic_route_gate_ignores_option_labels_for_route_choice(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    decision = deterministic_hermes_route_gate(
        "Task: run a local JSONL dataset smoke check. Options: self, air5, specialist."
    )

    assert decision["route"] == "self"
    assert decision["reason"] == "run a local JSONL dataset smoke check."


def test_deterministic_route_gate_requires_explicit_task_and_options(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    assert deterministic_hermes_route_gate("Answer a short math question.") is None
    assert deterministic_hermes_route_gate("Task: inspect a 24B model.") is None
    assert deterministic_hermes_route_gate("Options: self, air5, specialist.") is None


def test_deterministic_route_dispatch_packet_exposes_canonical_state(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    packet = deterministic_hermes_route_dispatch_packet(
        "Task: run a local JSONL dataset smoke check. Options: self, air5, specialist."
    )

    assert packet == {
        "packet_state": "route_decided",
        "status": "ready_for_dispatch",
        "source": "deterministic_gate",
        "route": "self",
        "escalation": "l0_executor",
        "reason": "run a local JSONL dataset smoke check.",
        "retry_count": 0,
        "unresolved_risks": [],
    }


def test_deterministic_route_gate_text_exposes_public_decision_only(monkeypatch):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)

    text = deterministic_hermes_route_gate_text(
        "Task: inspect a 24B safetensors coding model and design a conversion runner. "
        "Options: self, air5, specialist."
    )

    assert json.loads(text) == {
        "reason": "inspect a 24B safetensors coding model and design a conversion runner.",
        "route": "specialist",
        "source": "deterministic_gate",
    }


def test_background_command_short_circuits_explicit_route_gate_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_OUTBOX_DISABLED", raising=False)
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_OUTBOX_DIR", str(tmp_path / "outbox"))

    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj._background_task_counter = 0
    cli_obj._background_tasks = {}

    outputs = []

    with (
        patch("cli._cprint", side_effect=lambda text="", *args, **kwargs: outputs.append(text)),
        patch.object(cli_obj, "_ensure_runtime_credentials", side_effect=AssertionError("credentials not needed")),
    ):
        cli_obj._handle_background_command(
            "/background Task: inspect a 24B safetensors coding model and design a conversion runner. "
            "Options: self, air5, specialist."
        )

    assert cli_obj._background_task_counter == 0
    assert cli_obj._background_tasks == {}
    assert any("Background route gate complete" in line for line in outputs)
    packet = json.loads(outputs[-1])
    assert packet["packet_state"] == "route_decided"
    assert packet["status"] == "ready_for_dispatch"
    assert packet["route"] == "specialist"
    assert packet["escalation"] == "l2_mario"
    assert packet["retry_count"] == 0
    assert packet["unresolved_risks"] == []
    assert packet["outbox_path"].startswith(str(tmp_path / "outbox"))

    outbox_path = tmp_path / "outbox" / packet["outbox_path"].rsplit("/", 1)[-1]
    assert outbox_path.exists()
    saved_packet = json.loads(outbox_path.read_text())
    assert saved_packet["dispatch_id"].startswith("hermes_route_")
    assert saved_packet["packet_state"] == "route_decided"
    assert saved_packet["status"] == "ready_for_dispatch"
    assert saved_packet["route"] == "specialist"
    assert saved_packet["outbox_owner"] == "hermes"
    assert saved_packet["target_authority"] == "imac_mario"
    assert saved_packet["target_node"] == "imac"
    assert saved_packet["raw_child_data"] is False
    assert saved_packet["privacy_class"] == "operator_route_packet"
    assert saved_packet["export_boundary"] == "route_metadata_only"
    assert saved_packet["route_plan"] == {
        "route": "specialist",
        "escalation": "l2_mario",
        "source": "deterministic_gate",
    }
    assert saved_packet["expected_receipt"]["required"] is True
    assert "output_sha256" in saved_packet["expected_receipt"]["fields"]


def test_background_route_gate_can_skip_outbox_write(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_PRIMARY", raising=False)
    monkeypatch.delenv("HERMES_ROUTE_DISPATCH_DISABLED", raising=False)
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_OUTBOX_DISABLED", "1")
    monkeypatch.setenv("HERMES_ROUTE_DISPATCH_OUTBOX_DIR", str(tmp_path / "outbox"))

    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj._background_task_counter = 0
    cli_obj._background_tasks = {}

    outputs = []

    with (
        patch("cli._cprint", side_effect=lambda text="", *args, **kwargs: outputs.append(text)),
        patch.object(cli_obj, "_ensure_runtime_credentials", side_effect=AssertionError("credentials not needed")),
    ):
        cli_obj._handle_background_command(
            "/background Task: inspect a 24B safetensors coding model and design a conversion runner. "
            "Options: self, air5, specialist."
        )

    packet = json.loads(outputs[-1])
    assert "outbox_path" not in packet
    assert not (tmp_path / "outbox").exists()
