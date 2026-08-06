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
    # SSRC of a channel radiod already starts at boot (e.g. a conf-declared
    # [channel] section), if this node has one. When set, set_frequency()
    # retasks this known-good, already-alive channel directly instead of
    # dynamically creating a new one via ensure_channel()/create_channel().
    # rtlsdr-v4 needs this: a brand-new dynamic channel on that instance
    # bootstraps at freq=0, below the hardware's tunable floor, and the
    # follow-up command that would move it to a real frequency never gets
    # applied or acknowledged -- confirmed root cause, see
    # docs/mcp-validation-evidence.md, "rtlsdr-v4 Root Cause: freq=0
    # Bootstrap Trap in radiod" and the direct-retask confirmation entry
    # right after it (0.053s clean success vs. every dynamic-channel
    # attempt timing out).
    boot_ssrc: int | None = None


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
        stage = "connect"
        ssrc: int | None = None
        try:
            control = ka9q.RadiodControl(status_address=status_address)

            if node.boot_ssrc is not None:
                # Retask the node's known, already-alive boot-time channel
                # directly -- skips ensure_channel()/create_channel()
                # entirely, avoiding the freq=0 dynamic-channel bootstrap
                # trap this path exists to work around. See RadiodNode.boot_ssrc.
                ssrc = node.boot_ssrc
            else:
                stage = "allocate channel"
                ssrc = self._ensure_ssrc(control, frequency_hz=frequency_hz, preset=preset)

            stage = "tune"
            # Prefer tune() when available; fallback to explicit setters for older APIs.
            if hasattr(control, "tune"):
                control.tune(ssrc=ssrc, frequency_hz=frequency_hz, preset=preset, timeout=5.0)
            else:
                control.set_frequency(ssrc=ssrc, frequency_hz=frequency_hz)
                if hasattr(control, "set_preset"):
                    control.set_preset(ssrc=ssrc, preset=preset)
        except Exception as exc:
            detail = f"radiod command failed on {node.node_id} during {stage}"
            if ssrc is not None:
                detail += f" (ssrc={ssrc})"
            if stage == "tune":
                # The rtlsdr-v4 failure mode: create_channel()/ensure_channel()
                # already created the channel server-side (radiod logs
                # "dynamically started ssrc ..."), but this confirmation wait
                # timed out before frequency/preset were verified applied. The
                # channel is left parked (often at its create-time defaults)
                # and self-expires (~20s) if nothing tunes it again -- so this
                # is not a no-op failure, it's a real unconfirmed state.
                detail += (
                    ". The channel was created/located but tune() never "
                    "confirmed it landed on the requested frequency/preset; "
                    "it may be left parked and will self-expire (~20s) if "
                    "untouched. Retry, or raise the tune() timeout if this "
                    "happens consistently on this node."
                )
            raise RuntimeError(f"{detail}: {exc}") from exc
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
        """Get or create a channel SSRC for (frequency_hz, preset).

        ensure_channel() is tried first -- it can reuse an existing channel
        and verifies the result. If it fails (including a verification
        timeout *after* it already created the channel server-side, the
        rtlsdr-v4 failure mode: radiod logs "dynamically started ssrc ..."
        but the confirmation reply doesn't reach the client in time), fall
        back to create_channel(), which is fire-and-forget and doesn't wait
        for a status reply.

        Unlike the old version of this method, create_channel()'s branch is
        no longer bare -- a failure there used to propagate uncaught past
        this function (and past the caller's generic "unable to allocate"
        message once both branches were exhausted), discarding whatever
        ensure_channel() had already reported. Both branches now fail loud
        with a specific message, and the ensure_channel() error is kept
        instead of silently swallowed so the full failure chain is visible.
        """
        ensure_error: Exception | None = None
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
                ensure_error = RuntimeError(
                    f"ensure_channel() returned no usable SSRC (raw result: {result!r})"
                )
            except Exception as exc:
                ensure_error = exc

        if hasattr(control, "create_channel"):
            try:
                result = control.create_channel(frequency_hz=frequency_hz, preset=preset)
            except Exception as exc:
                suffix = f" after ensure_channel() also failed ({ensure_error})" if ensure_error else ""
                raise RuntimeError(
                    f"create_channel() failed for freq={frequency_hz} preset={preset}{suffix}: {exc}"
                ) from exc
            ssrc = self._extract_ssrc(result)
            if ssrc is not None:
                return ssrc
            raise RuntimeError(
                f"create_channel() returned no usable SSRC for freq={frequency_hz} "
                f"preset={preset} (raw result: {result!r})"
            )

        if ensure_error is not None:
            raise RuntimeError(
                f"unable to allocate or discover channel SSRC for freq={frequency_hz} "
                f"preset={preset}: ensure_channel() failed and no create_channel() "
                f"fallback is available on this ka9q-python build ({ensure_error})"
            ) from ensure_error
        raise RuntimeError(
            f"unable to allocate or discover channel SSRC for freq={frequency_hz} "
            f"preset={preset}: neither ensure_channel() nor create_channel() is "
            "available on this ka9q-python build"
        )
