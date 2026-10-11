# Open WebUI setup
Open WebUI is available at `https://<hostname-ip>:8443/`.

## Deployment details
The container has one read-write mount, `open-webui-state:/app/backend/data`,
plus a read-only `/data/audio` for transcription. The Kismet, occupancy,
SigID, and MAC-vendor data is read by the optional MCP server in its own
sandboxed container, not by Open WebUI. Collection databases, Kismet files,
packet captures, and SDR data are never mounted because SIGedge owns them.

The image is pinned in `containers/open-webui.container` (currently
`v0.12.0`); see [operations.md](operations.md#upgrade-safely) to change it.

Open WebUI binds to `127.0.0.1:8080` in the host network namespace. Its
Ollama URL is Caddy's private route:
`http://127.0.0.1:8180/ollama`.

Native tools call the gateway through
`http://127.0.0.1:8180/gateway`. The gateway still enforces bearer roles;
Caddy's loopback binding is an additional network boundary, not a replacement
for application authorization.

Any additional mount is a `Volume=` line in `containers/open-webui.container`
itself. Quadlet drop-ins are not used: Podman 4.x ignores them. Podman refuses
to start the container if a mount's source directory is missing, so run
`install-corpus-dirs.sh` first. See [optional-tools.md](optional-tools.md).

When Caddy's internal CA is used, export its root certificate after first
startup and trust it on every client:

```bash
podman cp caddy:/data/caddy/pki/authorities/local/root.crt ./sigliere-root-ca.crt
```

## Install native tools

In Open WebUI, open **Workspace → Tools**, create a tool, and paste each file:

1. `openwebui-tools/sigedge_status_tool.py`
2. `openwebui-tools/sigint_operator_tool.py`

No external OpenAPI or MCP connection is required for the core install. The
optional read-only MCP server is described in
[optional-tools.md](optional-tools.md#mcp-server-optional); Open WebUI v0.12
lists tool and MCP connections under **Tools → Integrations**.

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

## Recommended Open WebUI settings for a sovereign deployment

Reviewed on `dungeon` against Open WebUI v0.12.0. `containers/open-webui.container`
sets these off through `Environment=` lines, but stored settings override
environment variables (they only seed a fresh install), so on an existing host
apply them in **Admin Panel → Settings**.

| Setting | Recommended | Why |
|---|---|---|
| Connections → **OpenAI API** | Off | Enabled by default with base URL `https://api.openai.com/v1`. Even with an empty key, Open WebUI sends `GET /v1/models` on each model-list refresh (it only skips the call when the connection is disabled). Ollama stays on. |
| Version update check | Off | The backend queries GitHub. Environment variable `ENABLE_VERSION_UPDATE_CHECK=False`. |
| Community sharing | Off | Offers sharing to the public Open WebUI community. |
| Web search, image generation, direct connections | Off | Already off on `dungeon`; keep them off. |
| Code interpreter and code execution | Off | An analysis model does not need to run code. Also untick the capability on each model. |
| Models → Capabilities | Untick Web Search, Image Generation, Code Interpreter, Terminal | Prevents accidental use if a global feature is enabled later. |
| Signup | Off, default role `pending` | Already set. |

Model layout used on `dungeon`: an **Analyst** model (MCP tools, status,
Whisper; no operator tool) and an **Operator** model (adds the operator tool),
both with function calling set to `native` and the system prompt from
[SIGINT-analyst-mcp.system-prompt.md](../openwebui-prompts/SIGINT-analyst-mcp.system-prompt.md).
Models with no access grants are private to their owner and admins; grant the
Analyst model to a group when other users need it and keep the Operator model
admin-only. Preferably the Operator model carries only the status and operator
tools, so a model that reads RF-derived text (SSIDs, device names) cannot also
tune a receiver.

### Qwen3 thinking mode

Open WebUI only sends `think` to Ollama if it is set in the model's advanced
parameters, so Qwen3 runs with thinking on by default. Measured with
`qwen3:14b`, 13 tool-selection questions x 3 seeds:

| Thinking | Correct first tool (native / MCP) | Mean latency per decision | Output tokens |
|---|---|---|---|
| off (`think: false`) | 39/39 / 39/39 | 0.7 s | about 25 |
| on (default) | 38/39 / 38/39 | 8.3 s / 8.7 s | about 350 |

Thinking does not improve tool selection here, and costs roughly ten times the
latency per decision; MCP and native behave the same either way. Set the
model's advanced parameter `think` to `false` for faster tool use, or leave it
on if you value the reasoning in the final answer. A chat turn with a tool
call involves at least two model calls.

## Optional SIGINT analyst tools

Optional tools support analyst investigations:

- MAC-vendor lookup using a local IEEE OUI/CID mirror (served by MCP).
- SigID signal lookup using a local sigidwiki mirror (served by MCP).
- Kismet device presence and occupancy (served by MCP).
- On-demand Whisper transcription (a native tool).

For a model that uses the MCP tools, use
[SIGINT-analyst-mcp.system-prompt.md](../openwebui-prompts/SIGINT-analyst-mcp.system-prompt.md)
and keep function calling set to native.

See [optional-tools.md](optional-tools.md) for installing the MCP server (the
recommended path for the data tools), the native fallback tools, and the
mounts they need.

