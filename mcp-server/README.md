# Sigliere MCP Server Bootstrap

This directory bootstraps a role-aware control plane for radiod-managed SDR nodes.

## What is included

- `config/nodes.json`: physical SDR node map and frequency boundaries.
- `src/sigliere_mcp_server.py`: zero-trust API surface plus MCP tool registrations.
- `src/radiod_adapter.py`: radiod and ka9q-python adapter layer.
- `src/operator_cli.py`: operator-side Python CLI to query nodes and issue tune changes.
- `Containerfile`: container build recipe.
- `.env.example`: environment variable template.
- `mcp.env.example`: host-side environment template for the Quadlet service.
- `openwebui-role-prompts.md`: copy-ready role provisioning prompts for Open WebUI.

## Security model

- Every request must carry a bearer token.
- Tokens map to roles from `SIGLIERE_MCP_TOKENS_JSON`.
- `analyst` role: read-only endpoints/tools.
- `operator` role: read + tuning actions.
- Requests are never trusted because of source network alone.

## Local run (host Python)

```bash
cd mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env values
set -a && source .env && set +a
python src/sigliere_mcp_server.py
```

## Container build and run

```bash
cd /home/baldrick/sigliere
podman build -f mcp-server/Containerfile -t localhost/sigliere-mcp:latest .
```

Create host env file at `~/.config/sigliere/mcp.env` (or copy `mcp.env.example`):

```bash
SIGLIERE_MCP_HOST=0.0.0.0
SIGLIERE_MCP_PORT=8140
SIGLIERE_MCP_DRY_RUN=true
SIGLIERE_MCP_TOKENS_JSON={"analyst-token":"analyst","operator-token":"operator"}
SIGLIERE_OPERATOR_TOKEN=operator-token
```

Enable quadlet:

```bash
mkdir -p ~/.config/containers/systemd
cp containers/sigliere-mcp.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user enable --now sigliere-mcp.service
```

## Open WebUI integration

Generate manual tool settings:

```bash
bash scripts/openwebui-mcp-command.sh
```

Use the printed URL and Authorization header in Open WebUI MCP tool settings.

Automated container validation:

```bash
cd /home/baldrick/sigliere
bash scripts/phase6-mcp-server-validate.sh
```

Optional host-side operator CLI usage:

```bash
cd /home/baldrick/sigliere/mcp-server
source .venv/bin/activate
export SIGLIERE_MCP_HOST=127.0.0.1
export SIGLIERE_MCP_PORT=8140
export SIGLIERE_OPERATOR_TOKEN=operator-token
python src/operator_cli.py nodes
python src/operator_cli.py route 144390000
python src/operator_cli.py tune hackrf-vhf-uhf 144390000 nfm
```

## Role provisioning prompts for Open WebUI

Use this sequence after the tool is registered:

1. Create user group: analyst (read-only MCP access).
2. Create user group: operator (read + set_frequency access).
3. Assign analyst users to analyst group only.
4. Assign trusted operators to operator group.
5. Store operator bearer tokens separately from analyst tokens.

## Notes

- Start with `SIGLIERE_MCP_DRY_RUN=true` for validation.
- Flip to `false` only after ka9q-python method compatibility is verified on your host.
- If Open WebUI native MCP remains incompatible in your version, you can keep using the existing OpenAPI server path in `openapi-tools/` while this MCP service is validated.
