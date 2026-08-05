from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from typing import Any


try:
    import ka9q  # type: ignore
except Exception:  # pragma: no cover
    ka9q = None


@dataclass(frozen=True)
class RadiodNode:
    node_id: str
    radiod_instance: str
    host: str
    port: int


class RadiodAdapter:
    """Small boundary layer around radiod and optional ka9q-python hooks."""

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def service_state(self, node: RadiodNode) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", f"radiod@{node.radiod_instance}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            active = (proc.stdout or "unknown").strip() or "unknown"
        except Exception as exc:  # pragma: no cover
            active = f"error:{exc.__class__.__name__}"

        socket_open = False
        try:
            with socket.create_connection((node.host, node.port), timeout=0.5):
                socket_open = True
        except OSError:
            socket_open = False

        return {
            "node_id": node.node_id,
            "service": f"radiod@{node.radiod_instance}",
            "active": active,
            "control_socket_reachable": socket_open,
        }

    def set_frequency(self, node: RadiodNode, frequency_hz: float, mode: str) -> dict[str, Any]:
        if self.dry_run:
            return {
                "dry_run": True,
                "node_id": node.node_id,
                "frequency_hz": frequency_hz,
                "mode": mode,
                "note": "Dry-run enabled; no radiod change was sent.",
            }

        if ka9q is None:
            raise RuntimeError(
                "ka9q-python is not importable. Install dependency or enable dry-run mode."
            )

        # ka9q-python interfaces differ between releases; keep this in a guarded
        # call so bootstrapping works and operators can adapt one location.
        try:
            client = ka9q.Client(host=node.host, port=node.port)
            client.set_frequency(frequency_hz)
            client.set_mode(mode)
        except Exception as exc:
            raise RuntimeError(f"radiod command failed: {exc}") from exc

        return {
            "dry_run": False,
            "node_id": node.node_id,
            "frequency_hz": frequency_hz,
            "mode": mode,
            "status": "applied",
        }
