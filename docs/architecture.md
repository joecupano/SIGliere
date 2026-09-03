# Architecture Model

## Overview
```text
                                  LAN browser
                                       |
                             HTTPS only, TCP 8443
                                       |
= = = = = = = = = = = = = = SIGliere = = = = = = = = = = = = = =
                                       |
                                       v
                         +---------------------------+
                         | Caddy TLS ingress         |
                         | LAN-facing :8443          |
                         | Internal CA or supplied   |
                         | certificate and key       |
                         +-------------+-------------+
                                       |
                              reverse proxy over
                                  loopback
                                       |
                                       v
                         +---------------------------+
                         | Open WebUI                |
                         | Rootless Podman           |
                         | 127.0.0.1:8080            |
                         +-------------+-------------+
                                       |
                              Open WebUI service traffic
                                       |
                                       v
                         +---------------------------+
                         | Caddy private router      |
                         | 127.0.0.1:8180            |
                         +-------------+-------------+
                                       |
                      +----------------+----------------+
                      |                                 |
             /ollama  v                       /gateway  v
        +--------------------+              +----------------------+
        | Ollama             |              | SIGedge gateway      |
        | Host service       |              | Rootless Podman      |
        | 127.0.0.1:11434    |              | 127.0.0.1:8140       |
        +--------------------+              +----------+-----------+
                                                      |
                                           KA9Q multicast
                                           status and control
                                                      |
= = = = = = = = = = = = = = SIGedge = = = = = = = = = = = = = =
                                                      |
                           +--------------------------+--------------------------+
                           |                          |                          |
                           v                          v                          v
                  +----------------+         +----------------+         +----------------+
                  | SIGedge node A |         | SIGedge node B |         | SIGedge node N |
                  | collection/DSP |         | collection/DSP |         | collection/DSP |
                  +----------------+         +----------------+         +----------------+

Security and integration boundaries:

- Only Caddy TCP 8443 is reachable from the LAN.
- Open WebUI, the private router, Ollama, and the gateway are loopback-only.
- Open WebUI reaches Ollama through `/ollama`; native tools reach the gateway
  through `/gateway`. Both use Caddy's loopback-only private router.
- There is no parallel external OpenAPI or MCP query service.
```

- SIGedge owns the complete collection tier: hardware, SDR and protocol
  capture, DSP, ka9q-radio, OpenWebRX+, Kismet, calibration, recordings, and
  collection storage.

- SIGliere owns model execution, user interaction, reasoning, and the
  API service needed to consume authorized SIGedge services.

The model is behavioral as well as organizational. SIGliere must not:

- read SIGedge radiod configuration files;
- invoke SIGedge systemd units;
- contain receiver models, gain settings, or device profiles;
- assume SIGedge is on the same host;
- mount collection databases or capture directories into Open WebUI.

## Networking

`gateway/config/nodes.json` version 1 declares logical node IDs, KA9Q status
multicast addresses, frequency ranges, modes, and whether control is allowed.
It deliberately contains no host path, systemd unit, radiod instance, or SDR
kind.

The gateway uses `ka9q-python` for status discovery and channel requests.
It starts in dry-run mode. Analyst and operator bearer tokens are independent,
and Open WebUI performs an additional live group check before operator calls.

Remote operation requires the two hosts to share a multicast-capable network
or have deliberate multicast routing. SIGedge must use a nonzero multicast TTL
and the correct egress interface. Switch IGMP snooping and firewall policy must
be tested with live status discovery.

## Host topology

```text
LAN browser
    |
    | HTTPS :8443
    v
Caddy TLS ingress (host network)
    |
    +-- reverse proxy --> 127.0.0.1:8080  Open WebUI
                                      |
                                      +-- Ollama API --> Caddy 127.0.0.1:8180/ollama
                                      |                   |
                                      |                   +--> 127.0.0.1:11434  Ollama
                                      |
                                      +-- native tool --> Caddy 127.0.0.1:8180/gateway
                                                          |
                                                          +--> 127.0.0.1:8140  gateway
                                                                    |
                                                             KA9Q multicast
                                                                    |
                                                              SIGedge nodes
```

Ports 8080, 8180, 11434, and 8140 are loopback-only. Port 8443 is the sole
application ingress.

