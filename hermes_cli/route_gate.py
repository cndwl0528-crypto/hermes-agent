"""Deterministic route gates for explicit Hermes operator prompts."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from utils import env_var_enabled


_ROUTE_ESCALATION = {
    "self": "l0_executor",
    "air5": "l1_hermes",
    "specialist": "l2_mario",
}


def route_dispatch_primary_enabled() -> bool:
    """Return True when explicit route packets should short-circuit dispatch.

    The route gate is already the primary path for explicit Task:/Options:
    background prompts.  The env var names the policy for operators while
    HERMES_ROUTE_DISPATCH_DISABLED remains a narrow emergency off switch.
    """
    if env_var_enabled("HERMES_ROUTE_DISPATCH_DISABLED"):
        return False
    if os.getenv("HERMES_ROUTE_DISPATCH_PRIMARY") is not None:
        return env_var_enabled("HERMES_ROUTE_DISPATCH_PRIMARY")
    return True


def _task_text(prompt: str) -> str:
    match = re.search(r"Task:\s*([\s\S]*?)(?:Options:|$)", prompt, flags=re.IGNORECASE)
    value = match.group(1) if match else prompt
    return " ".join(value.strip().split())


def deterministic_hermes_route_gate(prompt: str) -> Optional[Dict[str, Any]]:
    """Return a governed route decision for explicit ``Task:/Options:`` prompts.

    The gate is deliberately narrow.  It does not classify arbitrary background
    tasks; callers must opt in with both a ``Task:`` body and route ``Options:``.
    """
    if not route_dispatch_primary_enabled():
        return None

    text = str(prompt or "").strip()
    if not text:
        return None
    if not re.search(r"\bTask:\s*", text, flags=re.IGNORECASE):
        return None
    if not re.search(r"\bOptions:\s*", text, flags=re.IGNORECASE):
        return None

    task = _task_text(text)
    lower = task.lower()
    route = None
    if (
        "24b" in lower
        or "safetensors" in lower
        or "conversion" in lower
        or "convert" in lower
        or "cuda" in lower
        or "remote training" in lower
    ):
        route = "specialist"
    elif "macbook air" in lower or "air5" in lower or "ui" in lower:
        route = "air5"
    elif "local jsonl" in lower or "jsonl dataset" in lower or "local smoke" in lower:
        route = "self"

    if route is None:
        return None

    return {
        "reason": task or "route selected by deterministic gate",
        "route": route,
        "source": "deterministic_gate",
        "escalation": _ROUTE_ESCALATION[route],
    }


def deterministic_hermes_route_dispatch_packet(prompt: str) -> Optional[Dict[str, Any]]:
    decision = deterministic_hermes_route_gate(prompt)
    if decision is None:
        return None
    return {
        "packet_state": "route_decided",
        "status": "ready_for_dispatch",
        "source": decision["source"],
        "route": decision["route"],
        "escalation": decision["escalation"],
        "reason": decision["reason"],
        "retry_count": 0,
        "unresolved_risks": [],
    }


def deterministic_hermes_route_gate_text(prompt: str) -> Optional[str]:
    decision = deterministic_hermes_route_gate(prompt)
    if decision is None:
        return None
    public_decision = {
        "reason": decision["reason"],
        "route": decision["route"],
        "source": decision["source"],
    }
    return json.dumps(public_decision, ensure_ascii=False, separators=(",", ":"))
