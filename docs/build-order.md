# Build order

## Quickstart

Bare command sequence, in order. Each phase's full rationale, exit
criteria, and flagged unknowns are in the sections below — read those
before debugging a failure, not just this list. Only run install
scripts with `sudo` where shown; several are deliberately rootless.
All commands are executed from `~\sigliere`

## Phase 1 — select only the devices you actually have connected
```
sudo ./scripts/phase1-hardware-drivers.sh
```
Once completed, `reboot` the server. Once rebooted, run the following
commands:
```
./scripts/phase1-validate-sdrs.sh
./scripts/phase1-validate-protocol-tools.sh
```

## Phase 2 - install OS packages
```
sudo ./scripts/phase2-os-packages.sh
./scripts/phase2-validate.sh
```
Security hardening — recommended HERE, before Phase 3+ brings up any
network-facing service (Ollama, Open WebUI, OpenWebRX+). See
docs/security-hardening.md. Not phase-numbered — cross-cutting,
applies regardless of build progress.
```
sudo ./scripts/security-hardening.sh
./scripts/security-hardening-validate.sh
```

## Phase 3 - Install Ollama
```
sudo ./scripts/phase3-ollama.sh
./scripts/phase3-validate.sh
```

## Phase 4 - Install Open WebUI
We install plain HTTP :8000 by default:
```
./scripts/phase4-open-webui.sh
./scripts/phase4-validate.sh
```
For HTTPS see the TLS options below
   TLS options (optional):
     CADDY_TLS=1 ./scripts/phase4-open-webui.sh          # self-signed local CA, :8443
     CADDY_TLS=cert CADDY_CERT=… CADDY_KEY=… CADDY_HOSTNAME=… \
       ./scripts/phase4-open-webui.sh                    # your own certificate
   (see docs/security-hardening.md § Caddy for details + client trust steps)

## Phase 5 - AI Ingestion
```
./scripts/phase5-ai-ingest.sh
./scripts/phase5-validate.sh
```

## Phase 6.1 — Set up `radiod`
```
sudo ./scripts/phase6-ka9q-radio.sh
./scripts/phase6-ka9q-radio-validate.sh
```

## Phase 6.2 — Setup decoders
```
sudo ./scripts/phase6-decode-tools.sh
./scripts/phase6-decode-tools-validate.sh
```

## Phase 6.3 - Setup SIGid mirrion of SIGID Wiki
```./scripts/phase6-sigid-mirror.sh
./scripts/phase6-sigid-mirror-validate.sh
```

## Phase 6.4 — only if RTL-SDR is connected
```
sudo ./scripts/phase6-openwebrx.sh
```
Then add RTL-SDR devices manually if not already detected by OpenWebRX+
(: web UI -> Settings -> SDR devices)

Then we validate OpenWebRX+ install
```
./scripts/phase6-openwebrx-validate.sh
```

## Phase 6.5 - SigMF Writer
```
./scripts/phase6-sigmf-writer.sh
./scripts/phase6-sigmf-writer-validate.sh
```

## Phase 6.6 — occupancy DB schema/access-layer, then the `occupancy producer`
```
./scripts/phase6-occupancy-db-validate.sh
./scripts/phase6-occupancy-producer.sh
```
This installs a continuous systemd --user service that sweeps radiod's
channels into the occupancy DB, grows the sightings table; requires radiod already running

## Phase 6.7 — OpenAPI tool server (Open WebUI external tool connection path)
```
./scripts/phase6-openapi-tools.sh
```
Six core phases, each depending only on what came before it. The AI stack
(Phases 3–5) is built and proven independently of SIGINT-specific
software (Phase 6) so the SIGINT layer can lean on already-working
ingest/OCR/audio infrastructure instead of duplicating it. A seventh
phase (Phase 7 — RF/Protocol Security Tooling: Kismet, WiFi/BT capture)
was added later; it sits at the packet/protocol layer, deliberately
separate from Phase 6's spectrum-occupancy model, and depends only on the
base OS/toolchain from Phases 1–2.

## Phase 7 - Install Kismet
```
./scripts/phase7-kismet.sh
./scripts/phase7-kismet-refresh.sh
./scripts/phase7-kismet-validate.sh
```
