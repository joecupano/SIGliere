from __future__ import annotations

from dataclasses import dataclass
from typing import Any


try:
    import ka9q  # type: ignore
except Exception:  # pragma: no cover
    ka9q = None

# How long service_state() listens via ka9q.discover_channels_native()
# before concluding a node's radiod is unreachable. Confirmed live
# 2026-08-11: even 1.0s reliably found every channel on both this
# repo's nodes (5 on hackrf-2m, ~16 on rx888-hf); 1.5s adds a small
# margin without making the /radiod_status endpoint feel sluggish.
STATUS_DISCOVERY_SEC = 1.5


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
    # The mode this node's boot_ssrc channel starts in (matches the conf's
    # [global]/[channel] `mode =`). Used to reject mode requests that would
    # require a demod-type change on the live boot channel -- confirmed
    # separately broken (radiod never replies, same symptom as the freq=0
    # bug but a distinct cause) in docs/mcp-validation-evidence.md's
    # mode-change isolation test. Same-family mode changes (e.g. fm/nfm/wfm
    # among each other) are unaffected and stay reliable.
    boot_mode: str | None = None


class RadiodAdapter:
    """Small boundary layer around radiod and optional ka9q-python hooks."""

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def service_state(self, node: RadiodNode) -> dict[str, Any]:
        """Report whether radiod for this node looks alive.

        FIXED 2026-08-11 (see docs/mcp-validation-evidence.md): this used
        to shell out to `systemctl is-active radiod@<instance>`, which can
        never work -- sigliere-mcp runs inside a container with no
        systemd/systemctl at all (confirmed live: `which systemctl` finds
        nothing in that container), so this always returned
        "error:FileNotFoundError" regardless of the node's actual health.
        It also used to probe a plain TCP connection to node.host/node.port
        (127.0.0.1:5000/5001 in nodes.json), but nothing in this stack
        ever listens on those -- radiod exposes no TCP control port at all.

        Replaced with a real, container-safe signal:
        `ka9q.discover_channels_native()` against node.status_address --
        the same SDK call `_resolve_status_address()` below already
        trusted for discovery, now reused for liveness too. Confirmed
        live this session that a hand-rolled raw-socket multicast join
        (the first attempt at this fix) reliably received NOTHING, even
        with a 15s window and even using ka9q-python's own StatusListener
        -- this host's radiod publishes status with TTL=0 (loopback-only,
        confirmed via discover_channels_native's own "Multicast data
        restricted to localhost loopback only!" warning), which the SDK
        call handles correctly and raw sockets did not, for reasons not
        pinned down further. Rather than debug the raw-socket path
        deeper, this uses the already-correct, already-proven SDK
        function instead of re-solving a problem it already solves.
        """
        if ka9q is None or not hasattr(ka9q, "discover_channels_native"):
            active = False
        elif not node.status_address:
            active = False
        else:
            try:
                channels = ka9q.discover_channels_native(
                    node.status_address, listen_duration=STATUS_DISCOVERY_SEC
                )
                active = bool(channels)
            except Exception:
                active = False

        return {
            "node_id": node.node_id,
            "service": f"radiod@{node.radiod_instance}",
            "active": "active" if active else "inactive-or-unreachable",
            "control_socket_reachable": active,
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

        if node.boot_ssrc is not None and node.boot_mode is not None:
            boot_preset = self._mode_to_preset(node.boot_mode)
            if self._demod_family(preset) != self._demod_family(boot_preset):
                raise RuntimeError(
                    f"mode '{mode}' (preset '{preset}') would require a live demod-type "
                    f"change on {node.node_id}'s boot channel (ssrc={node.boot_ssrc}), "
                    f"away from its boot family (mode '{node.boot_mode}' -> preset "
                    f"'{boot_preset}'). Live demod-type changes on this node are "
                    "confirmed to hang/fail (radiod never replies) -- this is a separate, "
                    "unresolved gap from the freq=0 bootstrap issue this boot_ssrc path "
                    "was built to work around. See docs/mcp-validation-evidence.md, the "
                    "mode-change isolation test. Retry with a mode in the same family as "
                    f"'{node.boot_mode}' (e.g. fm/nfm/wfm together, or am/usb/lsb/cw/iq "
                    "together)."
                )

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

    # Presets that ka9q-radio's create_channel() classifies as DEMOD_TYPE 0
    # (linear); everything else (fm/nfm/wfm) is DEMOD_TYPE 1 (FM). Mirrors
    # that same classification (see mcp-server .venv's ka9q/control.py,
    # create_channel()) so we can tell whether a mode change would require
    # switching demod type on an already-running channel -- confirmed
    # broken for boot_ssrc channels, see docs/mcp-validation-evidence.md.
    _LINEAR_PRESETS = frozenset({"iq", "usb", "lsb", "cw", "am"})

    @classmethod
    def _demod_family(cls, preset: str) -> str:
        return "linear" if preset.lower().strip() in cls._LINEAR_PRESETS else "fm"

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
