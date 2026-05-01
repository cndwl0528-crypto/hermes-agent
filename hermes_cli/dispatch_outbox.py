"""Local dispatch outbox helpers for governed Hermes route packets."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home
from utils import atomic_json_write, env_var_enabled


def route_dispatch_outbox_enabled() -> bool:
    """Return True when route packets should be written to the local outbox."""
    return not env_var_enabled("HERMES_ROUTE_DISPATCH_OUTBOX_DISABLED")


def route_dispatch_outbox_dir() -> Path:
    configured = os.getenv("HERMES_ROUTE_DISPATCH_OUTBOX_DIR")
    if configured:
        return Path(configured).expanduser()
    return get_hermes_home() / "agent-floor" / "packets" / "outbox" / "hermes" / "open"


def write_route_dispatch_outbox_packet(
    packet: Dict[str, Any],
    *,
    prompt: str,
    now: Optional[datetime] = None,
) -> Optional[Path]:
    """Write a canonical route packet to the local outbox and return its path.

    This only creates local evidence. It does not perform remote SSH dispatch or
    Memory Palace admission.
    """
    if not route_dispatch_outbox_enabled():
        return None

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        f"{stamp}\n{packet.get('route', '')}\n{packet.get('reason', '')}\n{prompt}".encode("utf-8")
    ).hexdigest()[:12]
    dispatch_id = f"hermes_route_{stamp}_{digest}"
    output_packet = dict(packet)
    output_packet.update({
        "dispatch_id": dispatch_id,
        "created_at": timestamp.isoformat().replace("+00:00", "Z"),
        "outbox_owner": "hermes",
        "target_authority": "imac_mario",
        "target_node": "imac",
        "raw_child_data": False,
        "privacy_class": "operator_route_packet",
        "export_boundary": "route_metadata_only",
        "route_plan": {
            "route": packet.get("route"),
            "escalation": packet.get("escalation"),
            "source": packet.get("source"),
        },
        "expected_receipt": {
            "required": True,
            "fields": [
                "dispatch_id",
                "status",
                "target_node",
                "job_class",
                "output_ref",
                "output_sha256",
                "raw_child_data",
            ],
        },
    })
    path = route_dispatch_outbox_dir() / f"{dispatch_id}.json"
    atomic_json_write(path, output_packet, indent=2)
    return path
