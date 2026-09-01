# Sigliere TIERED project state

This branch separates cognition from collection.

Sigliere retains Ollama, Open WebUI, Caddy, native Python tools, and one
authenticated KA9Q multicast gateway. SIGedge owns the complete collection
tier, including SDR and protocol hardware, DSP, ka9q-radio, OpenWebRX+,
Kismet, calibration, captures, and collection storage.

Key rules:

- Caddy TLS on 8443 is the sole LAN application ingress.
- Ollama, Open WebUI, Caddy's private router, and the gateway are loopback-only.
- Caddy uses its internal CA unless a certificate and key are provided.
- Remote and same-host SIGedge use the same versioned node contract.
- Sigliere never reads SIGedge config files, systemd state, or device profiles.
- Open WebUI uses native tools; duplicate OpenAPI and MCP query paths are gone.
- Gateway control is token-gated, group-gated in Open WebUI, and dry-run first.

