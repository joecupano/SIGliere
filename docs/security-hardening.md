# Security

## Ingress

Caddy HTTPS on TCP 8443 is the only application port allowed from the LAN.
SSH remains allowed for administration. Open WebUI, Caddy's private router,
Ollama, and the SIGedge gateway bind to loopback on ports 8080, 8180, 11434,
and 8140 respectively.

Run:

```bash
sudo ./scripts/install-security-hardening.sh
./scripts/validate-security-hardening.sh
```

## Certificates

The default `tls internal` configuration encrypts traffic but requires each
client to trust Caddy's private root CA. An operator-provided certificate is
preferable when an existing trusted PKI is available. Private keys are copied
with mode 0600 into `~/.config/containers/systemd/caddy-certs`.

## Gateway authorization

The gateway uses separate analyst and operator bearer tokens and starts in
dry-run mode. The operator Open WebUI tool adds a live group-membership check.
Do not expose port 8140 directly or register it as a shared external tool
connection.

See [operations.md](operations.md) for token rotation, production control,
backup, and Caddy CA recovery.

## Multicast

Treat the SIGedge multicast network as sensitive. Prefer a dedicated VLAN,
enable IGMP snooping, limit TTL to the minimum required, and allow control
multicast only from authorized SIGliere hosts.

