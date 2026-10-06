# Project State

Last updated: 2026-09-09

SIGliere is the sovereign cognition tier for a SIGINT deployment. The current
repository implements the tiered design: SIGliere owns model execution, the
operator interface, AI-side processing, and a single authenticated gateway to
SIGedge. SIGedge owns all collection hardware, DSP, ka9q-radio, OpenWebRX+,
Kismet, calibration, captures, and collection storage.

This file describes the repository baseline. It does not assert that a
particular host has been installed or has passed live multicast validation.

## Fixed architecture and security rules

- Caddy TLS on TCP 8443 is the sole LAN application ingress.
- Ollama, Open WebUI, Caddy's private router, and the SIGedge gateway bind to
  loopback only.
- Caddy uses its internal CA unless an operator supplies a certificate and key.
- Remote and same-host SIGedge deployments use the same version 1 node contract.
- SIGliere does not read SIGedge configuration, systemd state, device profiles,
  capture databases, or collection files.
- Open WebUI integrates through native Python tools; there is no parallel MCP
  or external OpenAPI query path.
- Gateway access uses separate analyst and operator bearer tokens. Operator
  calls also check Open WebUI group membership, and control starts in dry-run.

## Implemented in the repository

### Core deployment

- Host prerequisite, corpus-directory, Ollama, gateway, Open WebUI/Caddy, and
  firewall installation scripts.
- Validation scripts for OS packages, Ollama, security boundaries, and the
  assembled tiered service path.
- Rootless Podman Quadlets for Caddy, Open WebUI, and the gateway.
- Mandatory HTTPS ingress with internal-CA and operator-certificate modes,
  including IP-literal deployments.
- A versioned SIGedge node contract with explicit multicast status addresses,
  frequency ranges, allowed modes, and per-node control policy.
- Authenticated gateway endpoints for health, node discovery, live status, and
  tuning. Frequency and mode requests are checked against the node contract.
- Native Open WebUI analyst and operator tools. The operator tool performs a
  live group-membership check on every control call.

### Optional local capabilities

- An idempotent document, image/OCR, and audio/Whisper ingest pipeline with a
  SQLite manifest and a four-hour user timer. Its normalized output is stored
  under `/data/corpus/processed`.
- Weekly local SigID and IEEE MAC-vendor mirrors, with installers, validators,
  manifests, and user timers.
- Native Open WebUI tools for SigID lookup, MAC-vendor lookup, and on-demand
  Whisper transcription. Their data mounts are intentionally opt-in.
- A local Open WebUI Knowledge/RAG workflow documented with an antenna-design
  example. This uses Open WebUI's native knowledge store, not the standalone
  ingest pipeline.
- An occupancy service (`occupancy/`) that polls the SIGedge gateway's
  `/status` endpoint and logs actively-demodulated channels into a local
  Kismet-schema SQLite database, with an installer/validator, a persistent
  `systemd --user` service, and a native Open WebUI query tool
  (`occupancy_tool.py`). Ported from the sovereign-sigint project's occupancy
  design — see "Occupancy capability added" below for what changed and why.
- A Kismet bridge (`kismet_bridge/`) — the third AI data source
  (occupancy/kismet/sigid) that was reserved but not built until now. New
  gateway endpoints (`GET /kismet/summary/{node_id}`,
  `GET /kismet/devices/{node_id}`) make a curated, per-request HTTP call to
  a node's Kismet REST API, authenticated with a per-node API key
  (`SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON`); a producer mirrors device
  presence into a local `kismet_bridge.db`; a native Open WebUI tool
  (`kismet_tool.py`) queries it. See "Kismet bridge capability added" below.

## Deployment work that remains operator-specific

1. `gateway/config/nodes.json`'s `sigedge-hf`, `sigedge-vhf-aprs`, and
   `sigedge-vhf-simplex` entries now hold SIGedge's fixed, checked-in static
   multicast addresses (status *and* data) and are live-verified on
   rubberduck (see status below). `sigedge-vhf-uhf` remains an intentional
   aspirational placeholder (unverified example address, no `data_address`)
   for a general-coverage receiver that doesn't exist yet — it is distinct
   from the two narrow real VHF nodes.
2. Run the installation and validation sequence in `INSTALL.md` on the target
   host.
3. Install the native tools in Open WebUI, assign their generated tokens, and
   configure the Operator group.
4. Verify live status multicast, routing/interface selection, TTL, IGMP
   behavior, and firewall policy. **Done for `sigedge-hf`, `sigedge-vhf-aprs`,
   and `sigedge-vhf-simplex` on rubberduck** — see "Live validation on
   rubberduck" below. `sigedge-vhf-uhf` is still not validated (no receiver
   backs it).
5. Exercise an authorized tune while dry-run is enabled. Disable
   `SIGLIERE_GATEWAY_DRY_RUN` only after status and authorization checks pass.
   Still open — rubberduck remains in dry-run.
6. Install and mount only the optional ingest/reference/occupancy
   capabilities that the deployment needs.

## Live validation on rubberduck (2026-09-04)

SIGliere core and SIGedge are both installed on rubberduck
(192.168.173.65). Findings and fixes from this pass:

- `scripts/validate-tiered.sh` passes all 7 checks, but only once
  `SIGLIERE_HOSTNAME` is set to the host's actual IP-literal address
  (`192.168.173.65` on rubberduck) — the script's default fallback
  (`$(hostname -s).local`) does not match how `install-open-webui.sh` was
  actually run on this host and produces a false-negative TLS-ingress
  failure. Persisted via `export SIGLIERE_HOSTNAME=192.168.173.65` in the
  operator's `~/.bashrc` on rubberduck; not yet reflected as a general
  fix in the script or `INSTALL.md`.
- The host firewall (`ufw`, installed by
  `scripts/install-security-hardening.sh`) had no exception for KA9Q
  multicast/UDP traffic, only `22/tcp` and `8443/tcp`. Added
  `sudo ufw allow proto udp to 239.0.0.0/8 comment 'KA9Q multicast
  (SIGedge)'` on rubberduck. This is host-specific state, not yet captured
  in the installer script itself.
- With `radiod@rx888-wwv` running (see SIGedge's own
  `SESSION_ISSUES_2026-09-04.md` for that side of the fix), the gateway's
  `/status/sigedge-hf` endpoint returns `"reachable": true"` with a live
  WWV channel and real SNR — the full SIGliere→gateway→KA9Q multicast path
  is confirmed working end-to-end for one node.
- Known gap carried forward: `radiod`'s multicast addresses are allocated
  dynamically per restart on this deployment (no static-address override
  configured on the SIGedge side yet), so `nodes.json`'s `sigedge-hf`
  address will go stale again the next time `radiod@rx888-wwv` restarts,
  the same way it already had before this session. See SIGedge's
  `SESSION_ISSUES_2026-09-04.md` for the recommended fix (adopt
  `NETWORKING.md`'s static-address scheme) before relying on this for
  anything long-running. **Resolved later the same day** — see below.

### Follow-up on rubberduck (2026-09-04, same day): static addressing adopted

SIGedge switched all three reference `radiod` instances
(`rx888-wwv`, `hackrf-aprs`, `rtlsdr-simplex`) to fixed, checked-in static
multicast addresses (`NETWORKING.md`'s scheme), closing the gap above. This
session imported that change into `nodes.json`:

- `sigedge-hf` repointed from the now-stale dynamic address
  (`239.113.183.73`) to the static `239.192.1.10` (status) /
  `239.192.64.10` (data).
- Two new nodes added for the two running VHF missions that didn't match
  `sigedge-vhf-uhf`'s wideband placeholder: `sigedge-vhf-aprs`
  (`239.192.1.20`/`239.192.64.20`, 144.390 MHz FM only) and
  `sigedge-vhf-simplex` (`239.192.1.30`/`239.192.64.30`, 144.650 MHz FM
  only). `sigedge-vhf-uhf` itself is left unchanged — still an aspirational
  placeholder for a real wideband receiver, not yet built.
- Diagnosed and fixed open item carried in `NEEDED-WORK.md`: with three
  simultaneous `radiod` instances live on rubberduck, `discover_channels_native`
  was confirmed to leak cross-node channels — querying one node's
  `status_address` sometimes returned another node's channel too (ka9q-python's
  native listener binds its socket to `INADDR_ANY:5006` and joins the
  requested multicast group, but does not filter *received* packets by
  destination address, so traffic for any other group already joined on the
  host's port 5006 gets delivered to it as well). Fixed in
  `sigedge_client.py`: `SigedgeNode` gained an optional `data_address` field
  (the node's known data-multicast address); `SigedgeClient.status()` now
  filters `discover_channels_native`'s result down to channels whose
  `multicast_address` actually matches it. `nodes.json` was updated with
  `data_address` for all three real nodes (not `sigedge-vhf-uhf`, which has
  no known data address). Covered by two new unit tests in
  `tests/test_sigedge_client.py`.
- Rebuilt and restarted the live `sigliere-gateway` container
  (`scripts/install-sigedge-gateway.sh`) so both the `nodes.json` edit and
  the `sigedge_client.py` fix took effect, then re-verified directly against
  the running container: `sigedge-hf`, `sigedge-vhf-aprs`, and
  `sigedge-vhf-simplex` each now report `reachable: true` with exactly their
  own channel (SSRC 10000/WWV, 144390/APRS, 144650/simplex respectively) and
  no cross-node bleed. `sigedge-vhf-uhf` (no `data_address`) still shows the
  old unfiltered behavior, consistent with it being an unverified
  placeholder rather than a real backed node.
- `scripts/validate-tiered.sh` re-run with `SIGLIERE_HOSTNAME=192.168.173.65`:
  all 7 checks still pass.
- `SIGLIERE_GATEWAY_DRY_RUN` remains `true` on rubberduck; no tune was
  exercised.

## Occupancy capability added (2026-09-04)

Ported sovereign-sigint's occupancy capability (`~/sovereign-sigint`) into
the repository as a new optional local capability, following the
sigid-mirror install/validate/systemd/tool pattern already established.
**Repository-only — not yet installed or live-validated on rubberduck**;
see "Known limitations" below.

- `occupancy/occupancy_schema.sql` and `occupancy_db.py`: the same Kismet
  DEVICES/PACKETS-derived `signals`/`sightings` schema and access layer as
  the original project, ported with only header/comment changes.
- `occupancy/occupancy_producer.py`: the actual design departure from the
  original. sovereign-sigint's producers read raw IQ/demodulator power
  directly off an SDR with a hand-calibrated dBFS threshold per
  device+antenna — forbidden here under the "Fixed architecture and
  security rules" above (SIGliere must not read SIGedge configuration,
  invoke its systemd units, or hold receiver/gain profiles). This producer
  instead polls the gateway's authenticated `/status` endpoint
  (`ka9q-python`'s `ChannelInfo`: frequency, preset, SNR — no raw samples,
  no gain/antenna knowledge) and records a sighting for every channel
  SIGedge currently reports as actively demodulated. There is deliberately
  no per-site calibration step: `snr` is recorded in `metadata_json` but
  not gated by default (`--min-snr-db` is opt-in, not a default threshold).
- `openwebui-tools/occupancy_tool.py`: self-contained native tool
  (`query_occupancy`, `occupancy_sightings`, `occupancy_summary`) reading
  `occupancy.db` directly with `sqlite3`, matching the other three optional
  tools' pattern (no import of repo modules, so it pastes cleanly into Open
  WebUI with no in-container checkout).
- `scripts/install-occupancy.sh` / `validate-occupancy.sh`,
  `systemd/occupancy.service`: installer/validator pair and a persistent
  `systemd --user` service (not a weekly timer like the mirrors —
  occupancy needs sub-minute polling cadence). Depends on the gateway
  already being installed, for its analyst token.
- `docs/occupancy-guide.md`: full design writeup, explicit about what
  carried over from sovereign-sigint versus what changed and why.
- 15 new unit tests (`tests/test_occupancy_db.py`,
  `tests/test_occupancy_producer.py`) covering signal-key binning, sighting
  aggregation, both JSON shapes the gateway can return channels in
  (dict-by-ssrc vs. list, per `gateway/tests/test_sigedge_client.py`'s own
  fakes), unreachable-node handling, and `--min-snr-db` filtering — all
  against faked gateway responses, no live network calls.
- Wired into `scripts/setup-venvs.sh` (new `occupancy` venv domain),
  `scripts/install-corpus-dirs.sh` (new `/data/occupancy` directory), and
  every doc that lists the other three optional tools (`INSTALL.md`,
  `README.md`, `docs/{data-layout,venvs,optional-tools,operations,README}.md`).

## Kismet bridge capability added (2026-09-09)

Built the third AI data source named but deliberately not built in
`occupancy_tool.py`'s own header comment ("no Kismet bridge exists in
SIGliere; that capability stays SIGedge-side"). Spec lived in
`KISMET-BRIDGE.md` at the repo root; see `docs/kismet-bridge-guide.md` for
the full design writeup. **Update 2026-10-06: installed and live-validated** against a standalone
Kismet 2025.09.0 server (`kismet-edge`, 192.168.9.74; WiFi, BTLE, ADS-B) —
see "Kismet bridge go-live" below.

- `gateway/src/sigedge_client.py`: `SigedgeNode` gained optional
  `kismet_host`/`kismet_port` fields and a `kismet_enabled` property. New
  `KismetClient` class — a genuinely different integration shape from
  `SigedgeClient`'s KA9Q multicast side: a real per-request HTTP call
  against Kismet's own REST API. Auth was verified against Kismet's
  current docs (<https://www.kismetwireless.net/docs/api/login/>) rather
  than assumed, resolving `KISMET-BRIDGE.md`'s open question in favor of a
  `readonly`-role API key (sent as the `KISMET` cookie) over HTTP Basic
  Auth — no session-cookie lifecycle needed for stateless per-request
  gateway calls. Exact device field paths and the POST body shape were
  sourced from Kismet's docs and the reference `python-kismet-rest`
  client, not validated against a live Kismet instance — flagged in the
  client's own comment as the one real unverified piece, the same posture
  `occupancy_db.py`'s `FREQUENCY_BIN_HZ` comment already takes toward its
  own open question.
- `gateway/src/sigedge_gateway.py`: new
  `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` env var (node_id -> API key,
  parallel to `SIGLIERE_GATEWAY_TOKENS_JSON`), new curated
  `GET /kismet/summary/{node_id}` and `GET /kismet/devices/{node_id}`
  endpoints (analyst role), and `kismet_enabled` added to `/nodes`'
  per-node response so the producer can discover which nodes to poll
  without guessing. A node with no `kismet_host` set 409s from both new
  endpoints; an unknown `node_id` still 404s.
- `kismet_bridge/kismet_bridge_schema.sql` + `kismet_bridge_db.py`: a new,
  deliberately separate device-centric schema — a single `devices` table
  keyed on `(node_id, mac)`, upserted per poll, not an event log like
  occupancy's `signals`/`sightings` split. A WiFi/BT device has a durable
  MAC address, which is exactly the identity RF signals lack — the reason
  occupancy needed frequency-binning in the first place.
- `kismet_bridge/kismet_bridge_producer.py`: matches
  `occupancy_producer.py`'s shape (`argparse` + `requests`, same analyst
  token file, `--once`/continuous/`--node`). Discovers Kismet-enabled
  nodes via the gateway's `/nodes` when `--node` isn't given. Default
  poll interval is 60s — meaningfully shorter than sovereign-sigint's
  15-minute file-staging cadence, since the gateway's live HTTP call per
  poll has no file-copy race to design around, but still an unvalidated
  placeholder.
- `openwebui-tools/kismet_tool.py`: self-contained native tool
  (`query_wifi_devices`, `kismet_summary`), matching every other optional
  tool's no-repo-import pattern. Updated the "three AI sources" comment
  block in both `occupancy_tool.py` and `sigid_reference_tool.py` to point
  at it.
- `scripts/install-kismet-bridge.sh` / `validate-kismet-bridge.sh`,
  `systemd/kismet-bridge.service`: installer/validator pair and a
  persistent `systemd --user` service, mirroring occupancy's pair
  exactly. Wired into `scripts/setup-venvs.sh` (new `kismet-bridge` venv
  domain) and `scripts/install-corpus-dirs.sh` (new `/data/kismet-bridge`
  directory).
- 18 new unit tests (`tests/test_kismet_client.py`,
  `tests/test_kismet_bridge_db.py`, `tests/test_kismet_bridge_producer.py`)
  covering `KismetClient` auth/credential errors and summary aggregation,
  device upsert/query behavior including same-MAC-different-node rows, and
  producer node discovery/poll behavior — all against faked HTTP responses,
  no live network or Kismet calls. Also smoke-tested the actual FastAPI
  app (in an ad hoc venv with `fastapi`/`httpx` installed, not part of the
  repo's own test suite) via `TestClient`: `/nodes` reports
  `kismet_enabled` correctly, `/kismet/summary/{node_id}` 409s for a node
  without `kismet_host`, and 404s for an unknown `node_id`.
- Docs: new `docs/kismet-bridge-guide.md` (mirrors
  `docs/occupancy-guide.md`'s structure); updated `docs/architecture.md`,
  `docs/optional-tools.md`, `docs/data-layout.md`, `docs/venvs.md`,
  `docs/operations.md` (credential rotation section), `docs/README.md`,
  `gateway/README.md`, `INSTALL.md`, and the root `README.md`'s repository
  layout.

## Kismet bridge go-live (2026-10-06)

Kismet is a standalone package on its own host (`kismet-edge`), not part of
SIGedge and unrelated to radiod. Installed gateway, bridge poller, and the
Open WebUI tool; `validate-kismet-bridge.sh` passes.

- `SigedgeNode`'s radiod fields (`status_address`, `min_hz`, `max_hz`,
  `modes`) are now optional; a node needs `status_address` or
  `kismet_host`. New `radiod_enabled` flag (also on `/nodes`). `/status`
  skips Kismet-only nodes, `/status/{id}` 409s for them.
- Kismet bridge DB uses rollback-journal mode, not WAL: the Open WebUI
  container mounts it read-only, and a WAL DB can't be opened read-only once
  the writer closes it.
- `query_wifi_devices` excludes PHY `ADSB` by default (aircraft are ~88% of
  the mirror); `include_adsb=true` or `phy="ADSB"` opts in. `kismet_summary`
  reports `adsb_count` / `non_adsb_count`.
  `device_type` matching is case-insensitive and accepts `AP`/`client` as
  shorthand for `Wi-Fi AP`/`Wi-Fi Client` (a model passing the bare `AP`
  got zero results against Kismet's real type names). Naming a device_type
  also opts out of the ADS-B default exclusion. Results are slimmed (no row
  ids or metadata blob, ISO timestamps instead of epochs, compact JSON).
- Open WebUI mounts `/data/kismet-bridge` read-only. System prompt names the
  Kismet tool. Ollama needs `OLLAMA_CONTEXT_LENGTH=16384` (systemd drop-in)
  or the ~6900-token native-tool request is truncated at the 4096 default and
  the models never see the tools. Qwen3 14B calls the tools reliably; the
  Groq 8B model often refuses.
- `occupancy_db.py` switched from WAL to rollback journal for the same
  reason. The operator tool's node listing is now `list_controllable_nodes`
  (it collided with the status tool's `list_sigedge_nodes`; re-paste it into
  Open WebUI and re-save the models' tool selection if needed).

## Known limitations and follow-up

- Repository checks cannot replace live validation against the target SIGedge
  network and KA9Q services.
- `sigedge-hf`, `sigedge-vhf-aprs`, and `sigedge-vhf-simplex` now use
  SIGedge's static multicast addressing, which is stable across `radiod`
  restarts (confirmed on rubberduck 2026-09-04). Any *future* SIGedge node
  added to `nodes.json` should get a `data_address` from the same static
  scheme up front — without one, `SigedgeClient.status()` falls back to
  `discover_channels_native`'s raw (and, per the finding above, potentially
  cross-contaminated) result.
- `sigedge-vhf-uhf` remains an unverified aspirational placeholder — no
  general-coverage VHF/UHF receiver has been built to confirm or replace it.
- `scripts/validate-tiered.sh` and `scripts/install-open-webui.sh` both
  default `SIGLIERE_HOSTNAME` to `$(hostname -s).local`, which is wrong for
  any host actually deployed with an IP-literal `SIGLIERE_HOSTNAME` (as
  rubberduck was) unless the operator exports the same value again before
  every validator run. Worth fixing in the scripts themselves — e.g.
  recording the install-time value somewhere `validate-tiered.sh` can read
  it — rather than relying on operators to remember and re-export it.
- The standalone AI ingest output is not automatically indexed by Open WebUI;
  chat RAG currently uses Open WebUI's separate Knowledge feature.
- Automated ingest validation covers DOCX, image OCR, and spoken audio. A real
  scanned PDF still requires a manual test.
- Unit coverage is currently narrow: gateway client contract behavior, a
  SigID manifest fallback, and occupancy's schema/producer logic. Service,
  authorization, multicast, and container integration are covered by
  deployment validators rather than unit tests.
- Occupancy (`occupancy/`, `occupancy.service`) has not yet been installed
  or exercised against the live rubberduck gateway — verified only with
  unit tests against faked gateway responses (see "Occupancy capability
  added" above). `scripts/install-occupancy.sh` / `validate-occupancy.sh`
  still need a real run on rubberduck before this capability can be called
  live-verified, the same bar the gateway itself already cleared above.
- The Kismet bridge (`kismet_bridge/`, `kismet-bridge.service`) has never
  been exercised against a real Kismet instance — see "Kismet bridge
  capability added" above. Three specific things need live confirmation
  before this can be called production-ready: (1) `KismetClient`'s exact
  REST field paths and POST body shape, sourced from docs/reference-client
  code rather than a live Kismet response; (2) that no SIGedge node in
  `gateway/config/nodes.json` yet has `kismet_host`/`kismet_port` set or a
  matching `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` entry — an operator
  step, not a code gap; (3) the 60-second poll interval, an unvalidated
  placeholder like occupancy's `FREQUENCY_BIN_HZ`.

## Verification baseline

Verification performed on 2026-09-03:

- `python3 -m unittest discover -s tests -v`: 4 tests passed.
- Python compilation completed for `ai-ingest/`, `gateway/src/`,
  `openwebui-tools/`, `reference/`, and `tests/`.
- `bash -n scripts/*.sh` completed successfully.
- All relative Markdown links resolve.

No live host, container, GPU, Open WebUI, Ollama, or SIGedge multicast tests
were run as part of this documentation update.

Live validation performed on rubberduck on 2026-09-04 (see "Live validation
on rubberduck" above for detail):

- `scripts/validate-tiered.sh` (with `SIGLIERE_HOSTNAME=192.168.173.65`): all
  7 checks passed.
- Gateway `/nodes` and `/status/sigedge-hf` queried directly against the
  running `sigliere-gateway` container: `sigedge-hf` reachable, live WWV
  channel with real SNR returned via the gateway's own `ka9q-python` client.
- `SIGLIERE_GATEWAY_DRY_RUN` remains `true` on rubberduck; no tune was
  exercised this session.
- `sigedge-vhf-uhf` was not exercised — no VHF/UHF `radiod` instance was
  brought up during this session.

Follow-up verification performed on rubberduck later on 2026-09-04 (see
"Follow-up on rubberduck" above for detail):

- `python3 -m unittest discover -s tests -v`: 6 tests passed (2 new, covering
  `SigedgeClient.status()`'s cross-node `data_address` filtering and its
  legacy unfiltered fallback).
- `python3 -m json.tool gateway/config/nodes.json`, `python3 -m py_compile`
  on `gateway/src/sigedge_client.py` and `gateway/src/sigedge_gateway.py`,
  and `bash -n scripts/*.sh` all completed successfully.
- `scripts/install-sigedge-gateway.sh` rebuilt the `sigliere-gateway` image
  and restarted the live service; its own health check reported healthy.
- `scripts/validate-tiered.sh` (with `SIGLIERE_HOSTNAME=192.168.173.65`): all
  7 checks passed.
- Direct in-container check against the rebuilt gateway's own
  `GatewayState`/`SigedgeClient`: `sigedge-hf`, `sigedge-vhf-aprs`, and
  `sigedge-vhf-simplex` each returned `reachable: true` with exactly one
  channel — their own — confirming the cross-node filtering fix against all
  three real, simultaneously-running `radiod` instances.
- `SIGLIERE_GATEWAY_DRY_RUN` remains `true` on rubberduck; no tune was
  exercised.

Verification performed on 2026-09-04 (occupancy capability added, see
"Occupancy capability added" above) — repository checks only, no live host
or service run:

- `python3 -m unittest discover -s tests -v`: 21 tests passed (15 new, all
  against faked gateway responses).
- `python3 -m py_compile` on `occupancy/occupancy_db.py`,
  `occupancy/occupancy_producer.py`, and
  `openwebui-tools/occupancy_tool.py`: completed successfully.
- `bash -n` on `scripts/install-occupancy.sh` and
  `scripts/validate-occupancy.sh`: completed successfully.
- Not run: `scripts/install-occupancy.sh` / `validate-occupancy.sh`
  themselves against the live rubberduck gateway — see "Known limitations."

Verification performed on 2026-09-09 (Kismet bridge capability added, see
"Kismet bridge capability added" above) — repository checks only, no live
host, Kismet instance, or service run:

- `python3 -m unittest discover -s tests -v`: 39 tests passed (18 new).
- `python3 -m py_compile` on `gateway/src/sigedge_client.py`,
  `gateway/src/sigedge_gateway.py`, `kismet_bridge/kismet_bridge_db.py`,
  `kismet_bridge/kismet_bridge_producer.py`, and
  `openwebui-tools/kismet_tool.py`: completed successfully.
- `bash -n` on `scripts/install-kismet-bridge.sh` and
  `scripts/validate-kismet-bridge.sh`: completed successfully.
- `python3 -m json.tool gateway/config/nodes.json`: still valid (file
  itself unchanged — no real Kismet host/port was fabricated into it; see
  gateway/README.md's documented example instead).
- Additional smoke test beyond the repo's own suite: the FastAPI app
  imported and served requests correctly in an ad hoc venv with
  `fastapi`/`httpx` installed (`/nodes` includes `kismet_enabled`;
  `/kismet/summary/{node_id}` returns 409 for a node without
  `kismet_host` and 404 for an unknown `node_id`).
- Not run: `scripts/install-kismet-bridge.sh` /
  `validate-kismet-bridge.sh` themselves, and no call was made against a
  real Kismet REST API — see "Known limitations."
