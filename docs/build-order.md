# Build order

## 1. Host prerequisites

```bash
sudo ./scripts/install-os-packages.sh
./scripts/phase2-validate.sh
```

This installs rootless Podman, Python, TLS utilities, and basic host tools.
It installs no collection or DSP packages.

## 2. Ollama

```bash
sudo ./scripts/install-ollama.sh
./scripts/phase3-validate.sh
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

## 5. Firewall and validation

```bash
sudo ./scripts/security-hardening.sh
./scripts/security-hardening-validate.sh
./scripts/validate-tiered.sh
```

## 6. Open WebUI tools

Follow [openwebui-setup.md](openwebui-setup.md) to install the native SIGedge
status and operator tools and configure their tokens.

