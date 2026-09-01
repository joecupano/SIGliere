# Open WebUI deployment details

The core container has one persistent mount:
`open-webui-state:/app/backend/data`. Collection databases, Kismet files,
audio captures, and SDR data are not mounted because SIGedge owns them.

Open WebUI binds to `127.0.0.1:8080` in the host network namespace. Its
Ollama URL is Caddy's private route:
`http://127.0.0.1:8180/ollama`.

Native tools call the gateway through
`http://127.0.0.1:8180/gateway`. The gateway still enforces bearer roles;
Caddy's loopback binding is an additional network boundary, not a replacement
for application authorization.

Optional knowledge or reference integrations should be added as explicit
Quadlet drop-ins with the smallest necessary read-only mounts. They are not
core installation prerequisites.

