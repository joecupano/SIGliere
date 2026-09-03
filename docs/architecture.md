# Architecture Model

## Overview
```
                               LAN
                                |
                         HTTPS only :443
                                |
= = = = = = = = = = = SIGliere = = = = = = = = = = = = = = = = = = = = = =
                                |
                                v
                    +------------------------+
                    |         Caddy          |
                    |   LAN-facing ingress   |
                    |                        |
                    | TLS termination        |
                    | - Internal CA default  |
                    | - Operator cert option |
                    +-----------+------------+
                                |
                    loopback-only routing
                         127.0.0.1 / ::1
                                |
              +-----------------+------------------+
              |                                    |
              v                                    v
    +----------------------+             +----------------------+
    |      Open WebUI      |             |  Caddy internal     |
    |  Rootless Podman     |             |  loopback listener  |
    |  Loopback bind only  |             |  not LAN accessible |
    +----------+-----------+             +----------+-----------+
               |                                    |
               | Native Open WebUI tools only       |
               |                                    |
               +-------------------+----------------+
                                   |
                     +-------------+-------------+
                     |                           |
                     v                           |
            +------------------+                 |
            |      Ollama      |                 |
            |   Host service   |                 |
            | Loopback only    |                 |
            +------------------+                 |
                                                 |
= = = = = = = = = = = SIGedge = = = = = = = = = = = = = = = = = = = = = =  
                                                 |
                                                 v                                               
                                       +------------------------+
                                       |    SIGedge Gateway     |
                                       | Rootless Podman        |
                                       | Host network           |
                                       | Loopback bind only     |
                                       +-----------+------------+
                                                   |                                               |
                                                   |
                                             KA9Q multicast
                                             discovery/control
                                                   |
                            +----------------------+----------------------+
                            |                      |                      |
                            v                      v                      v
                    +---------------+      +---------------+      +---------------+
                    | SIGedge Node  |      | SIGedge Node  |      | SIGedge Node  |
                    |      A        |      |      B        |      |      N        |
                    | logical node  |      | logical node  |      | logical node  |
                    +---------------+      +---------------+      +---------------+

Security / Integration Boundaries
---------------------------------

LAN  --->  Caddy  --->  loopback services

NO LAN DIRECT ACCESS TO:
  - Open WebUI
  - Ollama
  - SIGedge Gateway
  - Host APIs

LLM INTEGRATION PATH:
  LLM
   |
   v
Open WebUI
   |
   +--> Native Open WebUI Tools --> Ollama
   |
   +--> Native Open WebUI Tools --> SIGedge Gateway

There is NO parallel:
  - OpenAPI query service
  - MCP query service
```

- SIGedge owns the complete collection tier: hardware, SDR and protocol capture,
DSP, ka9q-radio, OpenWebRX+, Kismet, calibration, recordings, and collection storage.

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
Caddy (host network)
    |-- 127.0.0.1:8080  Open WebUI
    |
    +-- 127.0.0.1:8180 private routes
          |-- /ollama  -> 127.0.0.1:11434
          +-- /gateway -> 127.0.0.1:8140

SIGedge KA9Q multicast
    |
    v
SIGedge gateway (host network)
```

Ports 8080, 8180, 11434, and 8140 are loopback-only. Port 8443 is the sole
application ingress.

