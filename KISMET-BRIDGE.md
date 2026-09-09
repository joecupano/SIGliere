# Kismet → AI Bridge — What Needs To Be Built

Spec for the third AI data source already reserved in code but not built:
`openwebui-tools/occupancy_tool.py`'s own header comment names the split —
*occupancy* (frequency activity, built), *kismet* (device/protocol presence,
this doc), *sigid* (the reference catalog, built) — and says plainly
"no Kismet bridge exists in SIGliere; that capability stays SIGedge-side."
This is what closing that gap actually requires.

SIGedge's side is already done and hardware-validated: Kismet itself,
built from source, running as a system service, capturing WiFi (a mainline
`mt76x2u` adapter), Bluetooth (Ubertooth One, firmware-upgraded), and
ISM-band RTL-SDR (`rtl433-sn-<serial>`, deliberately pinned against
`radiod`'s own use of the same hardware type). See SIGedge's own
`KISMET-CHECKLIST.md` for that full history. None of that changes here —
this document is exclusively about the SIGliere-side consumption layer.

## Why This Isn't a Direct Port of sovereign-sigint's Design

sovereign-sigint's bridge (`docs/kismet-to-ai-bridge.md` in that project)
is a single-host design: a timer stages the newest `.kismet` SQLite file to
a stable path, and a native Open WebUI tool reads that file directly,
read-only, from inside the same container on the same box. That doesn't
transfer here for the same reason `occupancy`'s port didn't transfer
directly either — [architecture.md](docs/architecture.md) is explicit that
SIGliere must not mount collection databases or capture directories, read
SIGedge configuration, invoke its systemd units, or assume SIGedge is on
the same host. There is no `.kismet` file to mount, because SIGliere is
never allowed to reach for it. The one lawful window into SIGedge is the
authenticated gateway (`gateway/src/sigedge_gateway.py`) — everything below
has to go through it, the same as `occupancy_producer.py` already does for
`radiod` status.

**The gateway today has zero Kismet awareness.** It's built specifically
around `ka9q-python` and KA9Q status/control multicast for `radiod` —
`/status`, `/status/{node_id}`, `/tune`, and their per-node config in
`gateway/config/nodes.json` (status/data multicast addresses, frequency
range, modes) have no equivalent path to a Kismet REST API at all. This
is new surface to add, not an existing one to reuse.

## What Actually Needs Building

Four pieces, mirroring the occupancy precedent's shape exactly
(gateway extension → producer → local schema → native tool), plus one
piece occupancy never needed: **credential handling**, because Kismet's
REST API requires authentication and KA9Q status multicast doesn't.

### 1. Gateway extension (`gateway/src/sigedge_gateway.py`, `sigedge_client.py`)

New, curated endpoints — **not** a raw proxy of Kismet's REST API. The
existing `/status` endpoint doesn't hand back everything KA9Q multicast
carries either; it returns a deliberately narrow shape (`ssrc`, `preset`,
`sample_rate`, `frequency`, `snr`, `multicast_address`). The Kismet
equivalent should be similarly curated, matching what
`sovereign_sigint_kismet_tool.py`'s two functions actually needed:

- `GET /kismet/summary/{node_id}` — device counts by type/PHY, capture
  time range (mirrors `kismet_summary`)
- `GET /kismet/devices/{node_id}` — device list with MAC, type, signal,
  SSID, manufacturer, first/last-seen (mirrors `query_wifi_devices`)

The gateway implements these by calling that node's Kismet REST API
directly (`http://<node-address>:2501/...`, HTTP basic auth per Kismet's
own web UI credential model — **verify this against Kismet's current REST
API docs before building**; recent Kismet versions may also support an
API-key mechanism distinct from the web UI's basic-auth login, which would
be the better fit if available). This is a genuinely different integration
shape than `/status`'s multicast listener — a real HTTP client call per
request, not a passively-aggregated subscription — and it's the correct
one: Kismet has no multicast status protocol to listen to.

Needs new per-node config in `nodes.json` — network address and port
reachable over the LAN/routed network (not a host path, systemd unit, or
device profile, so it doesn't cross the same line `nodes.json`'s existing
fields already avoid), plus a credential reference. Since not every
SIGedge node necessarily runs Kismet (a node might be `radiod`-only), this
should be an optional per-node field, not a change to every existing entry.

### 2. Credential handling — new surface, occupancy never needed this

KA9Q status multicast has no login. Kismet's REST API does. Where do
per-node Kismet credentials live? Follow `gateway.env.example`'s existing
pattern (`~/.config/sigliere/gateway.env`, never checked into git) rather
than inventing a new secrets mechanism — likely a
`SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` mapping `node_id` to
username/password (or API key, pending the verification above), parallel
to how `SIGLIERE_GATEWAY_TOKENS_JSON` already maps tokens to roles.
**Real, unresolved design question**: credential rotation and provisioning
— does an operator manually create a Kismet API-capable account for the
gateway to use per node, separate from their own personal web UI login?
Almost certainly yes, matching general least-privilege practice, but this
needs an actual decision and an `INSTALL.md` step, not an assumption.

### 3. Local mirror DB — device-centric, deliberately not `occupancy.db`

sovereign-sigint kept Kismet's device-centric data separate from the
frequency-centric occupancy DB on purpose ("two different kinds of
intelligence"). That reasoning holds here even more strongly, because
`occupancy_schema.sql` is itself already Kismet-schema-*derived*
(`DEVICES`/`PACKETS` → `signals`/`sightings`) for a completely different
question (frequency activity, not device presence) — reusing it would
conflate two designs that only superficially resemble each other. Build a
new `kismet_bridge/kismet_bridge_schema.sql` + access layer, matching
`occupancy_db.py`'s access-layer pattern: MAC, device type (AP/client/
bridged), SSID (for APs), manufacturer, signal, first/last-seen, and
(new, because SIGliere's gateway already serves *multiple* SIGedge
nodes, unlike sovereign-sigint's single-host design) a `node_id` column —
who observed this device matters once there's more than one Kismet
instance in the picture.

### 4. Producer (`kismet_bridge/kismet_bridge_producer.py`)

Match `occupancy_producer.py`'s shape closely: `argparse` + `requests`
against `http://127.0.0.1:8180/gateway`, `--once`/continuous/`--node`
flags, bearer token from the same gateway auth the occupancy producer
already uses (read-only "analyst" role is sufficient — this never needs
"operator"/control access). Polls `/kismet/summary/{node}` and
`/kismet/devices/{node}` per configured node, upserts into the local
mirror DB.

**Real opportunity, not just a port**: sovereign-sigint's 15-minute
refresh cadence existed specifically to work around *file staging*
(copying a live SQLite file safely without reading a half-written one).
That constraint doesn't exist here — the gateway makes a live HTTP call to
Kismet's REST API every poll, so there's no file-copy race to design
around at all. A meaningfully shorter interval is worth considering, sized
to actual Kismet REST API load rather than inherited from a workaround
that no longer applies.

### 5. Native Open WebUI tool (`openwebui-tools/kismet_tool.py`)

Match `occupancy_tool.py`'s exact conventions: self-contained (no imports
of repo-internal modules, pastable straight into Workspace → Tools),
`Valves` for the DB path as mounted inside the container, plain `sqlite3`
with `PRAGMA query_only=ON`, a `MAX_RESULTS` cap. Expose the same two
functions sovereign-sigint's original tool did —
`query_wifi_devices`/`kismet_summary` — reading the new local mirror
instead of a mounted `.kismet` file. Once built, update the "three AI
sources" comment block already sitting in both `occupancy_tool.py` and
`sigid_reference_tool.py` to point at it instead of "not built here."

## Open Questions To Resolve Before/While Building

- Kismet REST API auth: basic auth (assumed above) vs. an API-key
  mechanism — verify against the actual Kismet version SIGedge runs before
  committing to a credential shape.
- Exact credential storage/provisioning flow (see §2) — needs a real
  decision, not an assumption carried into `INSTALL.md`.
- Polling cadence (see §4) — no forcing constraint anymore; pick a number
  deliberately rather than inheriting sovereign-sigint's file-staging
  interval.
- Multi-node behavior: with more than one Kismet-capable SIGedge node,
  should the tool's queries default to "all nodes" or require `--node`
  explicitly, matching whatever convention `occupancy_tool.py` settled on
  for the same question.

## What Stays Exactly SIGedge's Job

Everything about Kismet itself: the systemd service, `kismet_site.conf`,
capture-source configuration (WiFi/Bluetooth/RTL-SDR), USB device
permissions, and the device-ownership discipline against `radiod`'s own
hardware use (SIGedge's `README.md` and `scripts/device-inventory.sh`).
None of it moves, none of it gets read directly by SIGliere, and this
bridge adds no new requirement on that side beyond "Kismet's REST API is
reachable on the network from wherever the gateway runs" — which it
already is, on :2501, per SIGedge's own `kismet_site.conf`.
