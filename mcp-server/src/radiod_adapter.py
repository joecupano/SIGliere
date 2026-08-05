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
    kind: str | None = None
    status_address: str | None = None


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

        if not hasattr(ka9q, "RadiodControl"):
            raise RuntimeError(
                "installed ka9q-python is missing RadiodControl; cannot issue live commands"
            )

        preset = self._mode_to_preset(mode)
        status_address = self._resolve_status_address(node)
        control = None
        try:
            control = ka9q.RadiodControl(status_address=status_address)
            ssrc = self._ensure_ssrc(control, frequency_hz=frequency_hz, preset=preset)

            # Prefer tune() when available; fallback to explicit setters for older APIs.
            if hasattr(control, "tune"):
                control.tune(ssrc=ssrc, frequency_hz=frequency_hz, preset=preset, timeout=5.0)
            else:
                control.set_frequency(ssrc=ssrc, frequency_hz=frequency_hz)
                if hasattr(control, "set_preset"):
                    control.set_preset(ssrc=ssrc, preset=preset)
        except Exception as exc:
            raise RuntimeError(f"radiod command failed: {exc}") from exc
        finally:
            if control is not None:
                try:
                    control.close()
                except Exception:
                    pass

        return {
            "dry_run": False,
            "node_id": node.node_id,
            "frequency_hz": frequency_hz,
            "mode": mode,
            "preset": preset,
            "status_address": status_address,
            "status": "applied",
        }

    def _resolve_status_address(self, node: RadiodNode) -> str:
        # Explicit per-node override wins.
        if node.status_address:
            return node.status_address

        if ka9q is None or not hasattr(ka9q, "discover_radiod_services"):
            return node.host

        try:
            services = ka9q.discover_radiod_services(timeout=2.0)
        except Exception:
            return node.host

        instance_tokens = [t for t in node.radiod_instance.lower().replace("_", "-").split("-") if t]
        kind_token = (node.kind or "").lower().strip()

        # Prefer exact-ish instance/kind matching over first-available fallback.
        for svc in services:
            if not isinstance(svc, dict):
                continue
            hay = f"{svc.get('name', '')} {svc.get('hostname', '')}".lower()
            if kind_token and kind_token in hay:
                return str(svc.get("address") or node.host)
            if any(tok in hay for tok in instance_tokens if len(tok) >= 3):
                return str(svc.get("address") or node.host)

        # Last resort: first discovered service address.
        for svc in services:
            if isinstance(svc, dict) and svc.get("address"):
                return str(svc["address"])

        return node.host

    @staticmethod
    def _mode_to_preset(mode: str) -> str:
        mapped = {
            "fm": "nfm",
            "nfm": "nfm",
            "wfm": "wfm",
            "am": "am",
            "usb": "usb",
            "lsb": "lsb",
            "cw": "cw",
        }
        return mapped.get(mode.lower().strip(), "iq")

    @staticmethod
    def _extract_ssrc(result: Any) -> int | None:
        if isinstance(result, int):
            return result
        if isinstance(result, dict) and "ssrc" in result:
            return int(result["ssrc"])
        if hasattr(result, "ssrc"):
            return int(getattr(result, "ssrc"))
        if isinstance(result, (tuple, list)) and len(result) > 0 and isinstance(result[0], int):
            return int(result[0])
        return None

    def _ensure_ssrc(self, control: Any, frequency_hz: float, preset: str) -> int:
        if hasattr(control, "ensure_channel"):
            try:
                result = control.ensure_channel(
                    frequency_hz=frequency_hz,
                    preset=preset,
                    timeout=5.0,
                )
                ssrc = self._extract_ssrc(result)
                if ssrc is not None:
                    return ssrc
            except Exception:
                pass

        if hasattr(control, "create_channel"):
            result = control.create_channel(frequency_hz=frequency_hz, preset=preset)
            ssrc = self._extract_ssrc(result)
            if ssrc is not None:
                return ssrc

        raise RuntimeError("unable to allocate or discover channel SSRC")
