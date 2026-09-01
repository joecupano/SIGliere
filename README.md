# Sigliere

Sigliere is the sovereign AI tier for a SIGINT deployment. It runs local
models through Ollama, provides the operator interface through Open WebUI,
and connects to the separate **SIGedge** collection tier through authenticated
Python tools and KA9Q multicast services.

Sigliere contains no SDR drivers, DSP applications, ka9q-radio installation,
OpenWebRX+, Kismet, capture services, or collection hardware configuration.
Those concerns belong exclusively to SIGedge.

## Architecture

- **Caddy** is the only LAN-facing service. HTTPS is mandatory. Installation
  uses Caddy's internal CA by default or an operator-provided certificate.
- **Open WebUI** runs as a rootless Podman container and binds to loopback.
- **Ollama** runs on the host and binds to loopback.
- **SIGedge gateway** runs as a rootless, host-networked Podman container and
  binds to loopback. It discovers and controls logical SIGedge nodes through
  KA9Q multicast.
- Caddy has a second loopback-only listener that routes Open WebUI to Ollama
  and the gateway. Host APIs are never exposed directly to the LAN.
- Native Open WebUI tools are the only LLM-facing integration path. There is
  no duplicate OpenAPI or MCP query service.

A remote SIGedge appliance and SIGedge installed on the same host use the
same versioned node contract in [gateway/config/nodes.json](gateway/config/nodes.json).
Co-location does not enable local service, filesystem, hardware, or radiod
configuration shortcuts.

## Quick start

Read [docs/build-order.md](docs/build-order.md). In summary:

```bash
sudo ./scripts/phase2-os-packages.sh
sudo ./scripts/phase3-ollama.sh
./scripts/install-sigedge-gateway.sh
./scripts/install-open-webui.sh
sudo ./scripts/security-hardening.sh
./scripts/validate-tiered.sh
```

Before installing the gateway, configure SIGedge's multicast addresses and
capabilities in `gateway/config/nodes.json`. A remote SIGedge must publish
KA9Q multicast with a TTL of at least 1 on the intended interface; `ttl=0`
is host-local.

## Repository layout

```text
gateway/             Versioned SIGedge contract, KA9Q client, gateway API
openwebui-tools/      Native analyst and operator tools
openwebui-prompts/    Model/system prompt configuration
containers/           Rootless Podman Quadlets and Caddy policy
scripts/              Core install, validation, and security scripts
docs/                 Architecture and operator documentation
```

