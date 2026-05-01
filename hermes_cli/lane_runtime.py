"""Runtime entrypoint mapping for Hermes lane policy."""

from __future__ import annotations

from typing import Any, Dict

from hermes_cli.config import get_lane_routing_config, load_config


_DEFAULT_ENTRYPOINTS: Dict[str, Dict[str, str]] = {
    "cli": {"stage": "normal_turn", "node": "air5", "risk": "low"},
    "cli_background": {"stage": "worker_task", "node": "air5", "risk": "medium"},
    "cli_btw": {"stage": "normal_turn", "node": "air5", "risk": "low"},
    "gateway": {"stage": "normal_turn", "node": "air5", "risk": "low"},
    "gateway_background": {"stage": "worker_task", "node": "air5", "risk": "medium"},
    "gateway_btw": {"stage": "normal_turn", "node": "air5", "risk": "low"},
}


def _string_dict(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if str(v).strip()}


def resolve_lane_kwargs(
    entrypoint: str,
    *,
    config: Dict[str, Any] | None = None,
    apply_model_map: bool = True,
) -> Dict[str, Any]:
    """Return AIAgent lane kwargs for a runtime entrypoint.

    Empty ``lane_routing`` maps preserve the existing concrete model/toolset
    behavior while still recording lane policy metadata on the agent.
    """
    source = config if config is not None else load_config()
    lane_cfg = source.get("lane_routing") if isinstance(source, dict) else {}
    if not isinstance(lane_cfg, dict):
        lane_cfg = {}
    if lane_cfg.get("enabled") is False:
        return {}

    defaults = _string_dict(lane_cfg.get("defaults"))
    entrypoints = lane_cfg.get("entrypoints")
    entry_cfg = {}
    if isinstance(entrypoints, dict):
        entry_cfg = _string_dict(entrypoints.get(entrypoint))

    base = dict(_DEFAULT_ENTRYPOINTS.get(entrypoint, _DEFAULT_ENTRYPOINTS["cli"]))
    base.update(defaults)
    base.update(entry_cfg)

    routing = get_lane_routing_config(source)
    return {
        "lane_stage": base.get("stage", "normal_turn"),
        "lane_node": base.get("node", "air5"),
        "lane_risk": base.get("risk", "low"),
        "lane_model_map": routing.get("model_map") if apply_model_map else {},
        "lane_runtime_map": routing.get("runtime_map") if apply_model_map else {},
        "lane_toolset_map": routing.get("toolset_map"),
    }


# === Lane A Mario Wiring P2 anchor (2026-04-29) ===
# Constitutional / harness anchors for runtime entrypoint -> lane stage mapping.
# Read-only references — these comments must not drift from upstream §:
#   "cli"                → IngressStage NORMAL_TURN
#                           (constitution-v1#3 Work stage; user terminal entry)
#   "cli_background"     → IngressStage WORKER_TASK
#                           (constitution-v1#3 Work stage executor lane)
#   "cli_btw"            → IngressStage NORMAL_TURN
#                           (constitution-v1#3 Work stage; "by the way" relay)
#   "gateway"            → IngressStage NORMAL_TURN
#                           (constitution-v1#3 Work stage; messaging-platform entry)
#   "gateway_background" → IngressStage WORKER_TASK
#                           (constitution-v1#3 Work stage executor lane)
#   "gateway_btw"        → IngressStage NORMAL_TURN
#                           (constitution-v1#3 Work stage; gateway "btw" relay)
# Mario role anchor:
#   resolve_lane_kwargs() returns AIAgent kwargs only; it does NOT pick Mario
#   itself. The Mario profile (Option A — ~/.hermes/profiles/mario/) is selected
#   upstream by `hermes_cli/main.py::_apply_profile_override` (see Lane A P2b
#   anchor). When the active profile is mario, the verdict-only judge lane
#   semantics from ~/.hermes/SOUL.md govern the agent's posture; this function
#   continues to return the same lane stage based on the entrypoint string.
# Bidirectional integrity (matrix v1 Block H row 3):
#   포괄: every constitution §3 stage that has a runtime entrypoint maps here.
#   보호: every entrypoint key cites a constitution § anchor + IngressStage.
# Forbidden: editing this anchor block from any packet other than Lane A
#            packets that explicitly include this file in allowed_files.
# === end anchor ===
