# Kismet → AI Bridge — Design and Status

Design record for the third AI data source named in
`openwebui-tools/occupancy_tool.py`'s header: *occupancy* (frequency
activity), *kismet* (device/protocol presence — this bridge), *sigid* (the
reference catalog). For day-to-day usage see
[docs/kismet-bridge-guide.md](docs/kismet-bridge-guide.md); this document
explains why the bridge is shaped the way it is and what has and hasn't been
verified.

**Status: built, installed, and validated live (2026-10-06)** against Kismet
2025.09.0 on `kismet-edge` (192.168.9.74), capturing WiFi (IEEE802.11), BTLE,
and ADS-B. `scripts/validate-kismet-bridge.sh` passes, and both
SIGINT-Qwen and SIGINT-Groq query it through Open WebUI.

Kismet is its own standalone package. It is **not** part of SIGedge (it was
deprecated from SIGedge) and has nothing to do with `radiod`. It runs on its
own host, installed per Kismet's own documentation. This document is
exclusively about the SIGliere-side consumption layer.

## Data Flow

```
Kismet REST :2501 ──► gateway (/kismet/summary, /kismet/devices)
                          ──► kismet_bridge_producer (poll every 60 s)
                                  ──► /data/kismet-bridge/kismet_bridge.db
                                          ──► kismet_tool.py in Open WebUI
                                              (read-only mount)
```

## Why This Isn't a Direct Port of sovereign-sigint's Design

sovereign-sigint's bridge is a single-host design: a timer stages the newest
`.kismet` SQLite file to a stable path, and a native Open WebUI tool reads it
directly, read-only, inside the same container on the same box. That doesn't
transfer here, for the same reason `occupancy`'s port didn't —
[architecture.md](docs/architecture.md) is explicit that SIGliere must not
mount collection databases or capture directories, or invoke remote systemd
units. Kismet runs on another host, so there is no `.kismet` file to mount.
The one lawful window to a remote collection host is the authenticated
gateway (`gateway/src/sigedge_gateway.py`), so everything goes through it,
the same as `occupancy_producer.py` does for `radiod` status.

## What Was Built

### 1. Gateway extension (`gateway/src/sigedge_gateway.py`, `sigedge_client.py`)

Two curated endpoints — deliberately **not** a raw proxy of Kismet's REST
API, matching `/status`'s own narrow-shape convention:

- `GET /kismet/summary/{node_id}` — device counts by type/PHY, capture time
  range
- `GET /kismet/devices/{node_id}` — device list with MAC, type, PHY, signal,
  SSID, manufacturer, first/last-seen

Both make a live HTTP call to the node's Kismet REST API per request
(`POST devices/last-time/0/devices.json`, form-encoded `json` field with a
field-simplification list). That is a genuinely different integration shape
from `/status`'s passively aggregated KA9Q multicast subscription, and the
correct one: Kismet has no multicast status protocol.

**Node contract.** `nodes.json` entries are independent per capability: a
radiod node declares `status_address` (plus range/modes), a Kismet node
declares `kismet_host`/`kismet_port`, and a node needs at least one. A
Kismet-only node such as `kismet-edge` has none of the radiod fields; it is
skipped by `/status` and rejected by `/status/{id}` (409) and `/tune`.
`/nodes` reports `radiod_enabled` and `kismet_enabled` per node. This is a
network address and port only — never a host path, systemd unit, or device
profile.

### 2. Credential handling

Resolved. Kismet's REST API requires authentication; the gateway uses a
pre-provisioned **`readonly`-role API key sent as the `KISMET` cookie**
(<https://www.kismetwireless.net/docs/api/login/>), verified live against
2025.09.0. An API key needs no session-cookie lifecycle across stateless
per-request calls and grants no write or control access.

Keys live in `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` (a `node_id` → key
map) in `~/.config/sigliere/gateway.env` — mode 600, never in git — parallel
to `SIGLIERE_GATEWAY_TOKENS_JSON`. Provisioning is a manual per-node step:
create a key for a role-limited account dedicated to the gateway, not an
operator's personal login. Rotation is covered in
[docs/operations.md](docs/operations.md#rotate-kismet-bridge-api-keys).

### 3. Local mirror DB — device-centric, deliberately not `occupancy.db`

`kismet_bridge/kismet_bridge_schema.sql` and `kismet_bridge_db.py`. Kept
separate from the frequency-centric occupancy DB on purpose: occupancy's
schema is itself Kismet-derived for a different question (frequency
activity), and reusing it would conflate two designs that only superficially
resemble each other. A WiFi/BT device has a durable MAC, so the mirror is one
`devices` row per `(node_id, mac)`, upserted each poll — a presence cache,
not an event log. `node_id` is a column because the gateway serves multiple
nodes.

**Journal mode is rollback (`DELETE`), not WAL.** The Open WebUI container
mounts the directory read-only, and a WAL database cannot be opened from a
read-only mount once the writer closes it and the `-wal`/`-shm` side files
disappear. (`occupancy_db.py` made the same change for the same reason.)

### 4. Producer (`kismet_bridge/kismet_bridge_producer.py`)

Matches `occupancy_producer.py`: `argparse` + `requests` against
`http://127.0.0.1:8180/gateway` (Caddy), `--once`/continuous/`--node`, the
read-only analyst bearer token. Without `--node` it asks `/nodes` which nodes
report `kismet_enabled` and polls those. Runs as `kismet-bridge.service`
(systemd `--user`).

The default interval is **60 seconds**, far shorter than sovereign-sigint's
15 minutes, because that cadence existed only to stage a live SQLite file
safely; a live REST call has no file-copy race. The number is a reasonable
placeholder, not one measured against Kismet REST load.

### 5. Native Open WebUI tool (`openwebui-tools/kismet_tool.py`)

Self-contained (no repo imports, pastable into Workspace → Tools), a
`KISMET_BRIDGE_DB_PATH` valve for the in-container path
(`/data/kismet-bridge-ref/kismet_bridge.db`), plain `sqlite3` with a
read-only URI connection, and a `MAX_RESULTS = 50` cap. Two tools, named for
continuity with the reference design:

- `query_wifi_devices` — filter by `mac`, `ssid`, `device_type`, `phy`,
  `node_id`, `since_minutes`. Despite the name it covers every PHY.
- `kismet_summary` — database-wide counts by type and PHY, time span, nodes.

Behavior worth knowing, all learned from live use:

- **ADS-B is excluded by default.** Aircraft were ~88% of the mirror (2289 of
  2593 devices) and would crowd everything else out of the 50-row cap. Pass
  `phy="ADSB"`, `include_adsb=true`, or name a `device_type` such as
  `Airplane` to include them. `kismet_summary` always reports `adsb_count`
  and `non_adsb_count` separately.
- **`device_type` is forgiving.** Case-insensitive, and `AP`/`client` are
  accepted as shorthand for Kismet's real names `Wi-Fi AP`/`Wi-Fi Client`.
  (The original docstring examples didn't match real data, and a model
  following them got zero results.)
- **Output is slimmed for small models:** no row ids or metadata blob, ISO
  timestamps instead of epochs, compact JSON, empty fields omitted.
- **Multi-node default:** `node_id` is optional; omitted, queries span all
  nodes.

### 6. Open WebUI deployment

The container mounts `/data/kismet-bridge` read-only at
`/data/kismet-bridge-ref` (`containers/open-webui.container`). The system
prompt (`openwebui-prompts/SIGINT-analyst.system-prompt.md`) names the tool,
says to call `kismet_summary` first, and states the ADS-B default.

**Ollama context length matters.** With native function calling, Open WebUI
sends a ~6900-token request (system prompt, all tool schemas, and its own
built-in tools). Ollama's 4096 default silently truncates it from the start,
so the model never sees the tools. Set `OLLAMA_CONTEXT_LENGTH=16384` in the
Ollama systemd unit. Tool-calling reliability also varies by model: Qwen3 14B
called the Kismet tools consistently; llama3-groq-tool-use 8B often refused
or skipped them.

## Decisions on the Original Open Questions

| Question | Outcome |
|---|---|
| Basic auth vs. API key | `readonly` API key as the `KISMET` cookie, verified live |
| Credential storage/provisioning | `gateway.env` map, manual per-node key; see operations.md |
| Polling cadence | 60 s, an unvalidated placeholder |
| Multi-node default | All nodes unless `node_id` is given |

## Known Limitations

- **Validated against one Kismet version and one node.** Multi-node behavior
  is implemented and unit-tested but has not run against a second live
  Kismet.
- **The 60 s poll interval is unmeasured.** Revisit with real polling data.
- **The mirror is a presence cache, not an event log.** Kismet remains the
  system of record for packet-level history; the mirror holds each device's
  latest state plus a `total_polls` counter.
- **Credential provisioning is manual,** once per Kismet node.

## What Stays Kismet's Job

Everything about Kismet itself: its service, configuration, capture-source
setup (WiFi/Bluetooth/ADS-B), and USB device permissions. SIGliere never
reads any of it directly. The bridge requires only that Kismet's REST API is
reachable from wherever the gateway runs (default port 2501) and that one
`readonly` API key exists.
