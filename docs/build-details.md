# Build details

## Single-tier Host networking
Open WebUI, Caddy, and the SIGedge gateway use host networking but their
application listeners bind to loopback. This gives the gateway reliable KA9Q
multicast access and lets Open WebUI reach Caddy's private routes without
publishing Ollama or gateway APIs on a LAN interface.

Caddy is the exception: its HTTPS listener on port 8443 is intentionally
LAN-facing. Its private listener on port 8180 is explicitly bound to
`127.0.0.1`.

## Caddy
Caddy provides mandatory TLS for the user interface and becomes the single
auditable ingress. It also gives local services stable private routes while
Ollama and the gateway remain loopback only.

`tls internal` uses Caddy's private CA. Clients must trust the exported root
certificate. When a certificate and key are supplied at installation, Caddy
uses those instead.

## Gateway
Gateway has one job: translate authenticated, logical SIGedge requests into
KA9Q multicast operations. Open WebUI exposes those operations only through
native tools. The gateway does not perform DSP and does not own collection
persistence.

