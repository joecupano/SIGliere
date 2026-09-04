# Project State

Last updated: 2026-09-04

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
6. Install and mount only the optional ingest/reference capabilities that the
   deployment needs.

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
- Unit coverage is currently narrow: gateway client contract behavior and a
  SigID manifest fallback. Service, authorization, multicast, and container
  integration are covered by deployment validators rather than unit tests.

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
