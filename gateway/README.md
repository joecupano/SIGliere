# SIGedge gateway

The gateway is Sigliere's only runtime adapter to the collection tier. It
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
the Sigliere host. `ttl=0` is host-local and cannot support a remote tier.

