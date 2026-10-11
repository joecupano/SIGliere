# Open WebUI setup
Open WebUI is available at `https://<hostname-ip>:8443/`.

## Deployment details
The container has one read-write mount, `open-webui-state:/app/backend/data`,
plus read-only mounts of SIGliere's own AI-tier data (the Kismet-bridge and
occupancy mirrors, the SigID and MAC-vendor reference mirrors, and
`/data/audio` for transcription). Collection databases, Kismet files, packet
captures, and SDR data are never mounted because SIGedge owns them.

The image is pinned in `containers/open-webui.container` (currently
`v0.12.0`); see [operations.md](operations.md#upgrade-safely) to change it.

Open WebUI binds to `127.0.0.1:8080` in the host network namespace. Its
Ollama URL is Caddy's private route:
`http://127.0.0.1:8180/ollama`.

Native tools call the gateway through
`http://127.0.0.1:8180/gateway`. The gateway still enforces bearer roles;
Caddy's loopback binding is an additional network boundary, not a replacement
for application authorization.

Optional integrations get the smallest necessary read-only mounts, declared
as `Volume=` lines in `containers/open-webui.container` itself. Quadlet
drop-ins are not used: Podman 4.x ignores them. Podman refuses to start the
container if a mount's source directory is missing, so run
`install-corpus-dirs.sh` first or delete the lines for tools you do not
install. See [optional-tools.md](optional-tools.md).

When Caddy's internal CA is used, export its root certificate after first
startup and trust it on every client:

```bash
podman cp caddy:/data/caddy/pki/authorities/local/root.crt ./sigliere-root-ca.crt
```

## Install native tools

In Open WebUI, open **Workspace → Tools**, create a tool, and paste each file:

1. `openwebui-tools/sigedge_status_tool.py`
2. `openwebui-tools/sigint_operator_tool.py`

No external OpenAPI or MCP connection is required. (Open WebUI v0.12 lists
tool and MCP connections under **Tools → Integrations**; SIGliere does not use
them.)

Read the generated tokens from `~/.config/sigliere/gateway.env`:

- Set `GATEWAY_ANALYST_TOKEN` on the SIGedge Status tool.
- Set `GATEWAY_OPERATOR_TOKEN` on the operator tool.
- Leave `GATEWAY_BASE_URL` at
  `http://127.0.0.1:8180/gateway`.

Create an `Operator` group in Open WebUI and add only authorized users. The
operator tool checks that group on every call. Administrators are allowed by
default; disable `ALLOW_ADMIN_ROLE` to require group membership for them too.
The configured group name must match the tool's `OPERATOR_GROUP_NAME` valve.

Create a custom model from `qwen3:14b` or `llama3-groq-tool-use:8b` under
**Workspace → Models**, then attach both tools. Apply the
[SIGINT analyst system prompt](../openwebui-prompts/SIGINT-analyst.system-prompt.md)
to keep the tier boundary explicit.

Test the model in this order:

1. Call `list_sigedge_nodes` with the status tool.
2. Call `sigedge_status`.
3. Call `list_controllable_nodes` with the operator tool.
4. Request a tune while the gateway is still in dry-run mode.

Keep `SIGLIERE_GATEWAY_DRY_RUN=true` until live multicast status and
authorization have both been verified. Follow the
[operations guide](operations.md#enable-or-disable-live-gateway-control) for
the production transition and rollback procedure.

## Optional SIGINT analyst tools

Three optional tools support analyst investigations:

- MAC-vendor lookup using a local IEEE OUI/CID mirror.
- SigID signal lookup using a local sigidwiki mirror.
- On-demand Whisper transcription.

See [optional-tools.md](optional-tools.md) for installation and read-only mount
instructions.

