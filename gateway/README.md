# SIGedge gateway

The gateway is SIGliere's only runtime adapter to the collection tier. It
uses `ka9q-python` against explicit KA9Q status multicast addresses and has
no knowledge of SDR hardware, radiod configuration files, SIGedge service
names, or SIGedge filesystem paths.

`config/nodes.json` is the versioned interface contract. A local SIGedge
installation and a remote SIGedge appliance use the same contract; only
multicast routing/interface configuration differs.

The gateway binds to loopback and is reached by the host-networked Open WebUI
container. Analyst tokens can list nodes and read live channel status.
Operator tokens can request tuning when both the node and gateway permit it.
The gateway installs in dry-run mode by default.

SIGedge must publish its status and channel multicast with a TTL that reaches
the SIGliere host. `ttl=0` is host-local and cannot support a remote tier.

## Kismet bridge

A Kismet server (device/protocol presence — WiFi, Bluetooth, ADS-B — see
the project root's `KISMET-BRIDGE.md`) is a standalone package, unrelated to
radiod. It is declared in `nodes.json` with `kismet_host`/`kismet_port` and
no radiod fields; a node without them has no Kismet capability, and a
Kismet-only node is skipped by `/status` and rejected by `/tune`:

```json
{
  "node_id": "kismet-edge",
  "kismet_host": "192.0.2.10",
  "kismet_port": 2501
}
```

This is, deliberately, the same category of fact `status_address` and
`data_address` already are: a network address+port, never a host path,
systemd unit, or device profile. Unlike KA9Q status, Kismet's REST API
requires authentication — see `gateway.env.example`'s
`SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` for how per-node API keys are
supplied. `GET /kismet/summary/{node_id}` and `GET /kismet/devices/{node_id}`
(analyst role) are curated endpoints, not a raw Kismet REST proxy — each
makes a live HTTP call to that node's Kismet instance per request, unlike
`/status`'s passively-aggregated multicast subscription. A node with no
Kismet fields set returns 409 from both.

