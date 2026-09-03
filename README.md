# SIGliere

SIGliere is the sovereign AI tier for a SIGINT deployment. It runs local
models through Ollama, provides the operator interface through Open WebUI,
and connects to the separate **SIGedge** collection tier through authenticated
Python tools and KA9Q multicast services.

SIGliere contains no SDR drivers, DSP applications, ka9q-radio installation,
OpenWebRX+, Kismet, capture services, or collection hardware configuration.
Those concerns belong exclusively to SIGedge.

## Architecture
See [docs/architecture.md](docs/architecture.md).

## Quick start

Read [INSTALL.md](INSTALL.md).
See the [documentation index](docs/README.md) for architecture, optional tools,
data layout, security, and operations.

If building a two-tiered deployment (separate hosts for SIGliere and SIGedge)
configure SIGedge's multicast addresses and capabilities in `gateway/config/nodes.json`.
A remote SIGedge must publish KA9Q multicast with a TTL of at least 1 on the
intended interface; `ttl=0` is host-local.

## Repository layout

```text
ai-ingest/           Optional document, image, and audio ingest pipeline
containers/          Rootless Podman Quadlets and Caddy policy
docs/                Architecture and operator documentation
gateway/             Versioned SIGedge contract, KA9Q client, and gateway API
openwebui-prompts/    Model and system-prompt configuration
openwebui-tools/      Native core and optional analysis tools
reference/            Optional SigID and MAC-vendor mirrors
scripts/              Installation, validation, and security scripts
systemd/              User services and timers for optional capabilities
tests/                Unit tests
```

