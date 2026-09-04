from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import ka9q  # type: ignore
except Exception:  # pragma: no cover - exercised by deployment preflight
    ka9q = None


@dataclass(frozen=True)
class SigedgeNode:
    node_id: str
    label: str
    status_address: str
    min_hz: float
    max_hz: float
    modes: tuple[str, ...]
    control_enabled: bool = False
    data_address: str | None = None


def _jsonable(value: Any) -> Any:
    """Convert ka9q-python result objects into FastAPI-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


class SigedgeClient:
    """KA9Q multicast client with no local SIGedge implementation knowledge."""

    def __init__(self, *, dry_run: bool = True, discovery_seconds: float = 1.5) -> None:
        self.dry_run = dry_run
        self.discovery_seconds = discovery_seconds

    @staticmethod
    def _require_ka9q() -> Any:
        if ka9q is None:
            raise RuntimeError("ka9q-python is not importable")
        return ka9q

    def status(self, node: SigedgeNode) -> dict[str, Any]:
        sdk = self._require_ka9q()
        if not hasattr(sdk, "discover_channels_native"):
            raise RuntimeError("ka9q-python lacks discover_channels_native")
        channels = sdk.discover_channels_native(
            node.status_address, listen_duration=self.discovery_seconds
        )
        # ka9q-python's native listener binds its socket to INADDR_ANY:5006 and
        # joins the requested status group, but on a host where other radiod
        # instances' groups are already joined (e.g. by other clients on the
        # same LAN), Linux delivers traffic for *all* joined groups on that
        # port to the wildcard-bound socket — it does not filter by
        # destination address. Confirmed live on rubberduck 2026-09-04:
        # querying one node's status_address returned channels whose
        # multicast_address belonged to a different radiod instance
        # entirely. When the node contract declares the node's own data
        # address, filter the result down to channels that actually belong
        # to it rather than trusting discover_channels_native's own scoping.
        if node.data_address:
            channels = self._filter_by_data_address(channels, node.data_address)
        normalized = _jsonable(channels)
        return {
            "node_id": node.node_id,
            "label": node.label,
            "status_address": node.status_address,
            "reachable": bool(channels),
            "channel_count": len(channels),
            "channels": normalized,
        }

    @staticmethod
    def _channel_data_address(channel: Any) -> str | None:
        if isinstance(channel, dict):
            value = channel.get("multicast_address")
        else:
            value = getattr(channel, "multicast_address", None)
        return str(value) if value else None

    @classmethod
    def _filter_by_data_address(cls, channels: Any, data_address: str) -> Any:
        if isinstance(channels, dict):
            return {
                ssrc: channel
                for ssrc, channel in channels.items()
                if cls._channel_data_address(channel) == data_address
            }
        if isinstance(channels, (list, tuple)):
            return [
                channel
                for channel in channels
                if cls._channel_data_address(channel) == data_address
            ]
        return channels

    def tune(self, node: SigedgeNode, *, frequency_hz: float, mode: str) -> dict[str, Any]:
        if not node.control_enabled:
            raise RuntimeError(f"control is disabled for {node.node_id}")
        mode = mode.lower().strip()
        if mode not in node.modes:
            raise ValueError(f"mode {mode!r} is not allowed for {node.node_id}")
        if not node.min_hz <= frequency_hz <= node.max_hz:
            raise ValueError(f"frequency is outside {node.node_id}'s declared range")
        if self.dry_run:
            return {
                "dry_run": True,
                "node_id": node.node_id,
                "frequency_hz": frequency_hz,
                "mode": mode,
            }

        sdk = self._require_ka9q()
        if not hasattr(sdk, "RadiodControl"):
            raise RuntimeError("ka9q-python lacks RadiodControl")
        control = sdk.RadiodControl(status_address=node.status_address)
        try:
            preset = "nfm" if mode == "fm" else mode
            if not hasattr(control, "ensure_channel"):
                raise RuntimeError("ka9q-python lacks ensure_channel")
            result = control.ensure_channel(
                frequency_hz=frequency_hz, preset=preset, timeout=5.0
            )
            ssrc = self._extract_ssrc(result)
            if ssrc is None:
                raise RuntimeError(f"ensure_channel returned no SSRC: {result!r}")
            control.tune(
                ssrc=ssrc, frequency_hz=frequency_hz, preset=preset, timeout=5.0
            )
        finally:
            close = getattr(control, "close", None)
            if close:
                close()
        return {
            "dry_run": False,
            "node_id": node.node_id,
            "frequency_hz": frequency_hz,
            "mode": mode,
            "preset": preset,
            "ssrc": ssrc,
            "status": "applied",
        }

    @staticmethod
    def _extract_ssrc(result: Any) -> int | None:
        if isinstance(result, int):
            return result
        if isinstance(result, dict) and result.get("ssrc") is not None:
            return int(result["ssrc"])
        if hasattr(result, "ssrc"):
            return int(result.ssrc)
        if isinstance(result, (tuple, list)) and result and isinstance(result[0], int):
            return result[0]
        return None

