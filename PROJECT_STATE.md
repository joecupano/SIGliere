# Project State

Last updated: 2026-09-03

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

1. Replace the example entries in `gateway/config/nodes.json` with the real
   SIGedge multicast addresses and capabilities.
2. Run the installation and validation sequence in `INSTALL.md` on the target
   host.
3. Install the native tools in Open WebUI, assign their generated tokens, and
   configure the Operator group.
4. Verify live status multicast, routing/interface selection, TTL, IGMP
   behavior, and firewall policy.
5. Exercise an authorized tune while dry-run is enabled. Disable
   `SIGLIERE_GATEWAY_DRY_RUN` only after status and authorization checks pass.
6. Install and mount only the optional ingest/reference capabilities that the
   deployment needs.

## Known limitations and follow-up

- Repository checks cannot replace live validation against the target SIGedge
  network and KA9Q services.
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
