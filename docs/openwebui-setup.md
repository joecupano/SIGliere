# Open WebUI setup

Open WebUI is available at `https://<configured-hostname>:8443/`.

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

Attach both tools to the desired model. Test in this order:

1. call `list_sigedge_nodes`;
2. call `sigedge_status`;
3. call the operator tool's `list_sigedge_nodes`;
4. request a tune while the gateway is still in dry-run mode.

Only change `SIGLIERE_GATEWAY_DRY_RUN=false` after live multicast status and
authorization have both been verified.

## Further optional tools

Three more native tools — MAC vendor lookup, SigID signal reference, and
on-demand Whisper transcription — are available but not required for a
core install. See [optional-tools.md](optional-tools.md).

