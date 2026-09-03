# Open WebUI setup
Open WebUI is available at `https://<hostname-ip>:8443/`.

# Deployment details
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

When Caddy's internal CA is used, export its root certificate after first
startup and trust it on every client:

```bash
podman cp caddy:/data/caddy/pki/authorities/local/root.crt ./sigliere-root-ca.crt
```

## Install native tools

In Open WebUI, open **Workspace → Tools**, create a tool, and paste each file:

1. `openwebui-tools/sigedge_status_tool.py`
2. `openwebui-tools/sigint_operator_tool.py`

No external OpenAPI or MCP connection is required.

Read the generated tokens from `~/.config/sigliere/gateway.env`:

- Set `GATEWAY_ANALYST_TOKEN` on the SIGedge Status tool.
- Set `GATEWAY_OPERATOR_TOKEN` on the operator tool.
- Leave `GATEWAY_BASE_URL` at
  `http://127.0.0.1:8180/gateway`.

The operator tool rechecks the caller's Open WebUI `Operator` group
membership on every call. Administrators are allowed by default; disable
`ALLOW_ADMIN_ROLE` to require group membership for administrators too.

Create a new model (Workspace > Models) from **qwen3:14B** or **llama3-groq-tool-use:8b**
Attach both tools to the new model. Test in this order in a chat
with the new model you have assigned the tools to:

1. call `list_sigedge_nodes`;
2. call `sigedge_status`;
3. call the operator tool's `list_sigedge_nodes`;
4. request a tune while the gateway is still in dry-run mode.

Only change `SIGLIERE_GATEWAY_DRY_RUN=false` after live multicast status and
authorization have both been verified.

## Optional SIGINT Analyst tools

Three tools are available to support SIGINT Analyst investigations:
- MAC vendor lookup (local mirror MAC vendor (OUI/CID) database.)
- SIGid signal reference (local mirrof of SIGidWiki.)
- On-demand Whisper transcription.

These are available but not required for a core install.
See [optional-tools.md](optional-tools.md).

