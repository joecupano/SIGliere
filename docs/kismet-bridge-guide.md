# Understanding and Using the Kismet Bridge

A standalone reference for the Kismet bridge capability in this build: what
it means, why it's shaped the way it is, and how to use it. This is the
third of the three AI data sources named in `occupancy_tool.py` and
`sigid_reference_tool.py` — the one that was reserved but not built until
now. The full build rationale lives in
[KISMET-BRIDGE.md](../KISMET-BRIDGE.md) at the repo root; this document
covers what's built and how to use it.

## What the Kismet Bridge Means

Device presence, not frequency activity and not signal identification.
Occupancy ([occupancy-guide.md](occupancy-guide.md)) answers "was this
frequency in use." The SigID reference
([optional-tools.md](optional-tools.md#sigid-reference)) answers "what is
this signal." The Kismet bridge answers a third, distinct question: **what
WiFi, Bluetooth, or ADS-B devices has a Kismet server actually seen, and
when.** Kismet is a standalone package (not part of SIGedge) running on its
own host.

## Why This Isn't a Direct Port of sovereign-sigint's Design

sovereign-sigint's bridge is a single-host design: a timer stages the
newest `.kismet` SQLite file to a stable path, and a native Open WebUI tool
reads it directly, read-only, from inside the same container on the same
box. That doesn't transfer here for the same reason occupancy's port
didn't transfer directly either — [architecture.md](architecture.md) is
explicit that SIGliere must not mount collection databases or capture
directories, or invoke remote systemd units. Kismet runs on another host,
so there is no `.kismet` file to mount. The one lawful window to a remote
host is the authenticated gateway
(`gateway/src/sigedge_gateway.py`) — everything here goes through it, the
same as `occupancy_producer.py` already does for `radiod` status.

## What's Built

**Gateway extension** (`gateway/src/sigedge_gateway.py`,
`gateway/src/sigedge_client.py`) — two curated endpoints, not a raw proxy
of Kismet's REST API: `GET /kismet/summary/{node_id}` (device counts by
type/PHY, capture time range) and `GET /kismet/devices/{node_id}` (device
list with MAC, type, signal, SSID, manufacturer, first/last-seen). Both
require a per-node `kismet_host`/`kismet_port` in `nodes.json` (optional —
a node without Kismet simply omits them) and make a live HTTP call to that
node's Kismet REST API per request — a genuinely different integration
shape from `/status`'s passively-aggregated KA9Q multicast subscription,
because Kismet has no multicast status protocol to listen to.

**Authentication** — verified against Kismet's own docs
(<https://www.kismetwireless.net/docs/api/login/>) rather than assumed:
Kismet supports pre-provisioned API keys scoped to a role (`readonly` is
the correct fit here — this bridge never needs write/control access),
sent as the `KISMET` cookie or URI parameter. `KismetClient` sends it as a
cookie. Keys live in `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON`
(`~/.config/sigliere/gateway.env`, never checked into git), mapping
`node_id` to API key — provision each with Kismet's own
`/auth/apikey/generate.cmd` against an account created for the gateway,
not an operator's personal login.

**Local mirror DB** (`kismet_bridge/kismet_bridge_schema.sql`,
`kismet_bridge/kismet_bridge_db.py`) — device-centric, deliberately not
`occupancy.db`, even though `occupancy_schema.sql` is itself
Kismet-schema-derived. A WiFi/BT device has a durable MAC address, which
most RF signals don't — so unlike occupancy's frequency-binned
`signals`/`sightings` event log, this mirror is a single `devices` table
keyed on `(node_id, mac)`, upserted on every producer poll rather than
appended to. `node_id` matters here in a way it didn't for
sovereign-sigint's single-host design — SIGliere's gateway already serves
multiple SIGedge nodes.

**Producer** (`kismet_bridge/kismet_bridge_producer.py`) — matches
`occupancy_producer.py`'s shape: `argparse` + `requests` against
`http://127.0.0.1:8180/gateway`, `--once`/continuous/`--node` flags, the
same analyst bearer token from `~/.config/sigliere/gateway.env`. Without
`--node`, it asks the gateway's `/nodes` endpoint which configured nodes
report `kismet_enabled` and polls exactly those. Polls
`/kismet/devices/{node}` per node and upserts into the local mirror.
Default interval is 60 seconds — meaningfully shorter than
sovereign-sigint's 15-minute cadence, because that cadence existed
specifically to safely stage a live `.kismet` SQLite file without reading
a half-written copy; the gateway's live HTTP call per poll has no
equivalent file-copy race to design around. Like occupancy's
`FREQUENCY_BIN_HZ`, this number is a reasonable placeholder, not one
validated against real Kismet REST load — revisit once real polling data
exists.

**Open WebUI tool** (`openwebui-tools/kismet_tool.py`) — reads
`kismet_bridge.db` directly with plain `sqlite3` (no import of
`kismet_bridge_db.py`; self-contained like every other native tool here).
Two tools, matching sovereign-sigint's original naming for continuity:
`query_wifi_devices` (filterable by MAC/SSID/type/PHY/node, despite the
name it covers every PHY Kismet tracks, not only WiFi) and
`kismet_summary` (database-wide counts by type/PHY). See
[optional-tools.md](optional-tools.md#kismet-bridge) for deployment.

## Install

```bash
./scripts/install-kismet-bridge.sh
./scripts/validate-kismet-bridge.sh
```

Requires the gateway already installed
(`./scripts/install-sigedge-gateway.sh`) — the producer authenticates with
its analyst token. Installs a persistent `systemd --user` service
(`kismet-bridge.service`), the same continuous-poller shape occupancy
uses, not a weekly-refresh timer.

## Honest Current Limitations

- **Validated against one Kismet version only.** The REST paths, POST body,
  and `readonly` API-key cookie were checked live on 2026-10-06 against
  Kismet 2025.09.0 (see `sigedge_client.py`'s `KismetClient` comment). Other
  Kismet versions may differ.
- **ADS-B dominates the mirror.** Aircraft are ~88% of devices, so
  `query_wifi_devices` excludes PHY `ADSB` by default; pass `phy="ADSB"` or
  `include_adsb=true` to include them. `kismet_summary` always reports
  `adsb_count` separately.
- **Journal mode is rollback, not WAL.** The Open WebUI container mounts the
  mirror read-only, and a WAL database cannot be opened from a read-only
  mount once the writer closes it.
- **The 60-second poll interval is an unvalidated placeholder**, same
  posture as occupancy's `FREQUENCY_BIN_HZ` — chosen as "meaningfully
  shorter than the file-staging cadence this replaces," not measured
  against real Kismet REST load.
- **Credential provisioning is a manual, per-node step.** There is no
  automated flow for creating a Kismet `readonly` API key and wiring it
  into `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` — an operator does this
  once per Kismet-capable node.
- **The local mirror is a presence cache, not an event log.** Unlike
  occupancy's `sightings` table, there is no per-poll detection history —
  Kismet itself remains the system of record for packet-level history;
  this mirror only tracks each device's latest known state plus a
  `total_polls` counter.

## See Also

- [KISMET-BRIDGE.md](../KISMET-BRIDGE.md) — the original build spec this
  guide reports against
- [architecture.md](architecture.md) — the tier boundary this design
  works within
- [gateway/README.md](../gateway/README.md#kismet-bridge) — the
  `/kismet/summary` and `/kismet/devices` endpoints this producer polls
- [optional-tools.md](optional-tools.md#kismet-bridge) — deployment as a
  native Open WebUI tool
- `kismet_bridge/kismet_bridge_schema.sql`, `kismet_bridge/kismet_bridge_db.py`,
  `kismet_bridge/kismet_bridge_producer.py` — the implementation
