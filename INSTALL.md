# Installation

## 1. Host prerequisites

```bash
sudo ./scripts/install-os-packages.sh
./scripts/validate-os-packages.sh
sudo ./scripts/install-corpus-dirs.sh
```

This installs rootless Podman, Python, TLS utilities, and basic host tools.
It installs no collection or DSP packages.

`install-corpus-dirs.sh` builds the whole `/data` corpus tree up front (see
[data-layout.md](docs/data-layout.md)) — not just the ai-ingest/reference-mirror
directories used by the optional capabilities described in section 8. Every
later step, including `install-ollama.sh`'s `/data/models`, assumes this tree
exists with the right ownership; running it here, before anything else
touches `/data`, keeps that assumption true instead of leaving it to
whichever script happens to touch `/data` first.

## 2. Ollama

```bash
sudo ./scripts/install-ollama.sh
./scripts/validate-ollama.sh
```

Ollama binds to `127.0.0.1:11434`. Model storage remains under
`/data/models`.

## 3. SIGedge contract and gateway

Edit `gateway/config/nodes.json` to match SIGedge's advertised status
multicast groups and capabilities, then run:

```bash
./scripts/install-sigedge-gateway.sh
```

The installer generates analyst and operator bearer tokens in
`~/.config/sigliere/gateway.env` and preserves that file on subsequent runs.
The gateway binds to `127.0.0.1:8140` and defaults to dry-run.

For a remote SIGedge, verify multicast reaches this host before enabling live
control. For same-host SIGedge, use the same contract and gateway; do not add
local shortcuts.

## 4. Open WebUI and Caddy

Default internal-CA certificate:

```bash
SIGLIERE_HOSTNAME=sigliere.example.local ./scripts/install-open-webui.sh
```

Operator-provided certificate:

```bash
SIGLIERE_HOSTNAME=sigliere.example.com \
SIGLIERE_CERT=/path/fullchain.pem \
SIGLIERE_KEY=/path/privkey.pem \
./scripts/install-open-webui.sh
```

The default is HTTPS on port 8443. There is no plain-HTTP LAN mode.

Isolated, DNS-less network (IP-only addressing):

```bash
SIGLIERE_HOSTNAME=192.0.2.10 ./scripts/install-open-webui.sh
```

`SIGLIERE_HOSTNAME` may be the host's LAN IP address instead of a DNS or
mDNS name. Caddy's internal CA issues the certificate with that IP as its
Subject Alternative Name, so operators browse straight to
`https://192.0.2.10:8443/` with no hosts-file entry or resolver required.
Each client still needs to trust the internal CA once (or click through the
browser warning) exactly as with a hostname deployment.

## 5. MCP server

The Kismet, occupancy, SigID, and MAC-vendor tools are served to Open WebUI by
a read-only MCP server (`mcp_server/`, [design](docs/mcp-server-design.md)).
It is part of the standard install: Open WebUI does not mount that data, so
without it those tools are unavailable. It needs the corpus directories from
step 1 and the `/mcp` route that step 4 generates:

```bash
./scripts/install-sigliere-mcp.sh
./scripts/validate-sigliere-mcp.sh
```

The installer creates `~/.config/sigliere/mcp.env` (mode 0600, the MCP token
only, no gateway credentials) and starts `sigliere-mcp.service` on
`127.0.0.1:8150`. The service starts fine before any data exists; its tools
report "no data" until the producers and mirrors in step 8 have run.

## 6. Firewall and validation

```bash
sudo ./scripts/install-security-hardening.sh
./scripts/validate-security-hardening.sh
./scripts/validate-tiered.sh
```

`validate-tiered.sh` reads the TLS hostname back from the installed Caddyfile,
so it matches whatever `SIGLIERE_HOSTNAME` you installed with. You can still
export `SIGLIERE_HOSTNAME` to override it. The Open WebUI installer waits for
Open WebUI itself (up to 3 minutes, longer than a typical start) before it
reports ready, so the validator can be run straight after it.

## 7. Open WebUI tools and the MCP connection

Follow [openwebui-setup.md](docs/openwebui-setup.md) to install the native SIGedge
status and operator tools, configure their tokens, and connect the MCP server
(Connection ID `mcp`). The Quadlet seeds Knowledge embeddings as
`nomic-embed-text` through Ollama for a fresh install; on an existing host set
**Admin Panel → Settings → Documents → Embedding Model Engine** to Ollama before
indexing anything (see [rag-knowledge-base-guide.md](docs/rag-knowledge-base-guide.md)).

## 8. Optional local capabilities

These components are not required for the core gateway and Open WebUI
deployment.

Install and validate scheduled document, image, and audio ingest:

```bash
./scripts/install-ai-ingest.sh
./scripts/validate-ai-ingest.sh
```

Install the local reference mirrors. Initial syncs require internet access:

```bash
./scripts/install-sigid-mirror.sh
./scripts/validate-sigid-mirror.sh
./scripts/install-mac-mirror.sh
./scripts/validate-mac-mirror.sh
```

Install occupancy (signals-heard logging against the live gateway; requires
step 3 above already done):

```bash
./scripts/install-occupancy.sh
./scripts/validate-occupancy.sh
```

Install the Kismet bridge (device-presence mirror against the live
gateway's Kismet endpoints; requires step 3 above already done, plus at
least one node with `kismet_host` set and a matching API key in
`SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` — see
[gateway/README.md](gateway/README.md#kismet-bridge) and
[KISMET-BRIDGE.md](KISMET-BRIDGE.md)):

```bash
./scripts/install-kismet-bridge.sh
./scripts/validate-kismet-bridge.sh
```

Open WebUI mounts only `/data/audio`; the Kismet, occupancy, SigID, and
MAC-vendor data is read by the MCP server installed in step 5. Follow
[optional-tools.md](docs/optional-tools.md) to install Whisper (and, if
wanted, the native fallback tools). For chat RAG,
follow [rag-knowledge-base-guide.md](docs/rag-knowledge-base-guide.md); the
standalone AI ingest output is not indexed by Open WebUI automatically.

## 9. Operations

Before enabling live gateway control, rotating tokens, backing up state, or
upgrading services, read [operations.md](docs/operations.md).
