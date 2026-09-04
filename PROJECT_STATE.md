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

1. `gateway/config/nodes.json`'s `sigedge-hf` entry is filled in with a
   live-verified multicast address on rubberduck (see status below).
   `sigedge-vhf-uhf` still holds an unverified example address — no VHF/UHF
   `radiod` instance has been brought up yet to confirm or replace it.
2. Run the installation and validation sequence in `INSTALL.md` on the target
   host.
3. Install the native tools in Open WebUI, assign their generated tokens, and
   configure the Operator group.
4. Verify live status multicast, routing/interface selection, TTL, IGMP
   behavior, and firewall policy. **Done for `sigedge-hf` on rubberduck** —
   see "Live validation on rubberduck" below. `sigedge-vhf-uhf` is not yet
   validated.
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
  anything long-running.

## Known limitations and follow-up

- Repository checks cannot replace live validation against the target SIGedge
  network and KA9Q services.
- `nodes.json` multicast addresses are only as stable as the SIGedge-side
  `radiod` configuration. Until SIGedge instances that SIGliere depends on
  use static multicast addressing (`NETWORKING.md`'s override scheme rather
  than the default mDNS-hashed dynamic allocation), a `radiod` restart can
  silently break gateway reachability until someone manually re-syncs
  `nodes.json`. See "Live validation on rubberduck" above.
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
