from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

try:
    import ka9q  # type: ignore
except Exception:  # pragma: no cover - exercised by deployment preflight
    ka9q = None


@dataclass(frozen=True)
class SigedgeNode:
    node_id: str
    label: str
    # radiod fields are optional: a Kismet-only node (Kismet is a standalone
    # package, unrelated to radiod/SIGedge) omits them all.
    status_address: str | None = None
    min_hz: float = 0.0
    max_hz: float = 0.0
    modes: tuple[str, ...] = ()
    control_enabled: bool = False
    data_address: str | None = None
    # Optional — Kismet is a standalone package, independent of radiod. A
    # node may have either or both. Per nodes.json's "no host
    # path/systemd unit/device profile" discipline, this is a network
    # address+port, the same category of fact status_address already is.
    kismet_host: str | None = None
    kismet_port: int | None = None

    @property
    def kismet_enabled(self) -> bool:
        return self.kismet_host is not None

    @property
    def radiod_enabled(self) -> bool:
        return self.status_address is not None


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
        if not node.radiod_enabled:
            raise RuntimeError(f"{node.node_id} has no radiod status_address configured")
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
        if not node.radiod_enabled:
            raise RuntimeError(f"{node.node_id} has no radiod to control")
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


# ---------------------------------------------------------------------------
# Kismet REST bridge
#
# A genuinely different integration shape from the KA9Q side above: a real
# HTTP client call per request against Kismet's own REST API, not a
# passively-aggregated multicast subscription — Kismet has no multicast
# status protocol to listen to.
#
# Auth: verified against Kismet's current docs
# (https://www.kismetwireless.net/docs/api/login/) rather than assumed.
# Kismet supports both HTTP Basic Auth (username/password, issuing a
# session cookie) and pre-provisioned API keys scoped to a role. An API
# key is the better fit here — it needs no session-cookie lifecycle across
# stateless per-request gateway calls, and can be provisioned as a
# standalone "readonly" role credential rather than a real login. Per
# Kismet's own docs: "API-token-only consumers of the API should provide
# ONLY the API token given, and supply it in the KISMET cookie or URI
# parameter." This client sends it as the KISMET cookie.
#
# Field paths and endpoint shapes below (POST with a form-encoded "json"
# field carrying the field-simplification spec, not a raw JSON body) are
# sourced from Kismet's own REST docs and the reference
# https://github.com/kismetwireless/python-kismet-rest client, and were
# validated live on 2026-10-06 against Kismet 2025.09.0 (readonly API key,
# devices/last-time/0/devices.json). Other Kismet versions are unverified.
class KismetClient:
    """Kismet REST API client — curated, not a raw proxy."""

    def __init__(
        self,
        credentials: dict[str, str] | None = None,
        *,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.credentials = credentials or {}
        self.timeout = timeout
        self.session = session or requests.Session()

    def _base_url(self, node: SigedgeNode) -> str:
        if not node.kismet_host:
            raise RuntimeError(f"{node.node_id} has no kismet_host configured")
        port = node.kismet_port or 2501
        return f"http://{node.kismet_host}:{port}"

    def _apikey(self, node: SigedgeNode) -> str:
        key = self.credentials.get(node.node_id)
        if not key:
            raise RuntimeError(
                f"no Kismet API key configured for {node.node_id} "
                "(SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON)"
            )
        return key

    def _post_fields(self, node: SigedgeNode, path: str, fields: list) -> Any:
        """POST one field-simplified request against Kismet's REST API.
        Kismet's POST convention is a form field named "json" carrying the
        serialized request body, not a raw JSON request body."""
        import json as _json

        url = f"{self._base_url(node)}/{path.lstrip('/')}"
        response = self.session.post(
            url,
            data={"json": _json.dumps({"fields": fields})},
            cookies={"KISMET": self._apikey(node)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # Fields shared by summary() and devices() — one underlying Kismet
    # call backs both curated gateway endpoints, matching /status's own
    # "one poll, one shaped response" pattern.
    _DEVICE_FIELDS = [
        ["kismet.device.base.macaddr", "mac"],
        ["kismet.device.base.phyname", "phy"],
        ["kismet.device.base.type", "type"],
        ["kismet.device.base.manuf", "manuf"],
        ["kismet.device.base.signal/kismet.common.signal.last_signal", "signal_dbm"],
        ["kismet.device.base.first_time", "first_time"],
        ["kismet.device.base.last_time", "last_time"],
        [
            "dot11.device/dot11.device.last_beaconed_ssid_record/"
            "dot11.advertisedssid.ssid",
            "ssid",
        ],
    ]

    def _fetch_devices(self, node: SigedgeNode) -> list[dict]:
        raw = self._post_fields(node, "devices/last-time/0/devices.json", self._DEVICE_FIELDS)
        return raw if isinstance(raw, list) else []

    def summary(self, node: SigedgeNode) -> dict[str, Any]:
        """Device counts by type/PHY and the capture time range — mirrors
        sovereign-sigint's kismet_summary()."""
        devices = self._fetch_devices(node)
        by_type: dict[str, int] = {}
        by_phy: dict[str, int] = {}
        first_times = []
        last_times = []
        for d in devices:
            by_type[d.get("type") or "unknown"] = by_type.get(d.get("type") or "unknown", 0) + 1
            by_phy[d.get("phy") or "unknown"] = by_phy.get(d.get("phy") or "unknown", 0) + 1
            if d.get("first_time"):
                first_times.append(d["first_time"])
            if d.get("last_time"):
                last_times.append(d["last_time"])
        return {
            "node_id": node.node_id,
            "device_count": len(devices),
            "by_type": by_type,
            "by_phy": by_phy,
            "first_seen_sec": min(first_times) if first_times else None,
            "last_seen_sec": max(last_times) if last_times else None,
        }

    def devices(self, node: SigedgeNode) -> dict[str, Any]:
        """Device list with MAC, type, signal, SSID, manufacturer,
        first/last-seen — mirrors sovereign-sigint's query_wifi_devices()."""
        return {"node_id": node.node_id, "devices": self._fetch_devices(node)}

