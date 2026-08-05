# OpenAPI to MCP Migration Notes

This note tracks how to switch Open WebUI integration from the current OpenAPI
external-tool path to the MCP path when Open WebUI MCP tooling support is
stable in your deployed version.

## Current state

- Open WebUI integration path in this build: OpenAPI (`:8130`).
- MCP server (`:8140`) is built and validated separately as a control-plane
  component.
- Evidence: see `docs/mcp-validation-evidence.md`.

## Keep using OpenAPI when

- Your Open WebUI tool connection type is OpenAPI-only.
- You need browser-side connection validation and stable external-tool setup.

## Switch to MCP when all are true

1. Your Open WebUI version supports MCP tool connections in your deployment.
2. MCP connection creation and invocation succeed end-to-end in your UI.
3. Analyst/operator role behavior is validated in your environment.

## MCP connection checklist

1. Ensure `sigliere-mcp.service` is active.
2. Generate MCP settings with `scripts/openwebui-mcp-command.sh`.
3. Register connection as Type=MCP in Open WebUI.
4. Confirm role checks:
   - analyst token can call read endpoints
   - analyst token cannot call `set_frequency`
   - operator token can call `set_frequency`
5. Record evidence in `docs/mcp-validation-evidence.md`.

## Rollback

If MCP registration or invocation fails in Open WebUI, revert to the OpenAPI
connection using:

- URL: `http://<box-lan-ip>:8130`
- OpenAPI spec: `http://<box-lan-ip>:8130/openapi.json`
- Auth: None (current service profile)
