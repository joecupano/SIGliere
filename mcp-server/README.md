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

The steps below (image build, env file, Quadlet) are automated by
`scripts/phase6-mcp-server-install.sh` — see Phase 6.9 in
`docs/build-order.md`. Prefer that script; it's idempotent (never
overwrites an existing `mcp.env`, rebuilds the image, and restarts the
service) and safe to re-run any time, including after a host reboot or
crash. The manual steps are kept here for reference:

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
systemctl --user restart sigliere-mcp.service
```

(Quadlet-generated units reject `systemctl --user enable` — "Unit is
transient or generated". Start-on-boot already comes from
`containers/sigliere-mcp.container`'s own `[Install]
WantedBy=default.target`, wired up by the generator on every
`daemon-reload`; use `start`/`restart` here, not `enable --now`.)

## Open WebUI integration

**As of 2026-08-12: the analyst connection is registered in Open
WebUI and confirmed working, including the Admin Panel's own live
browser-side connection test** (present in `user.settings.ui.toolServers`
with `enable: true`; `/openapi.json` and an authenticated `/nodes` call
both succeed). It initially failed the browser-side test — root cause
was the `ufw` gap described just below, fixed with `sudo ufw allow
8140/tcp`, retested and passing. If this ever regresses, the
service-side checks passing while the *browser's* connection test still
fails is the signature of that same firewall gap, not a bad connection
config. The operator (tuning) capability is a native in-process tool
instead —
`openwebui-tools/sigint_operator_tool.py` — not a registered connection
at all. See `openwebui-role-prompts.md` for why and the full setup
sequence; don't register an operator OpenAPI connection without reading
that first.

**`ufw` gotcha:** this build's `ufw` default-denies inbound, and no rule
for `8140/tcp` ships anywhere (unlike `:8130`, which
`scripts/phase6-openapi-tools.sh` explicitly checks for). Open WebUI
validates a Tool Server connection from the **browser**, which must
reach the host's LAN IP on `8140` — that request crosses the real
firewalled interface, whereas curling the same URL from this host or
from inside the `open-webui` container routes around it and succeeds
even when `ufw` is blocking everyone else. If the Admin Panel connection
test fails: `sudo ufw status | grep 8140` to confirm, then
`sudo ufw allow 8140/tcp`.
`scripts/phase6-mcp-server-install.sh` now warns about this
automatically (best-effort — it can't check without a cached `sudo`
credential).

**This registration does not survive an Open WebUI reset, and it's easy
to miss that it's gone.** In this build (0.11.0), Tool Server connections
made through Admin Panel → Settings → Tools → Tool Servers are stored
**per-user** (`user.settings.ui.toolServers` in `webui.db`), not in the
instance-wide config (`config` table's `tool_server.connections` key,
which stays `[]` regardless — don't check that key, it will never show
this). A fresh `open-webui-state` volume, a restored/reprovisioned
instance, or a different user account all start with an empty
`toolServers` list even while `sigliere-mcp.service` itself is healthy —
this happened once already (registered ~08:07 on 2026-08-11, gone after
that day's later reset, not caught until 2026-08-12). There's no install
script for this step; re-registering means repeating the "Generate the
analyst connection block" steps below by hand, in the browser, for
whichever user account needs it — verify explicitly if the MCP service
outage / reset history warrants it, don't assume DB or container health
implies this is still registered.

Generate the analyst connection block. This repo's actual Open WebUI
0.11.0 build only offers connection **Type = OpenAPI** (no MCP/Streamable
HTTP option in its Admin Panel), so use the OpenAPI-flavored script, not
the plain MCP one below:

```bash
bash scripts/openwebui-mcp-openapi-command.sh analyst
```

Paste the printed block into **Admin Panel → Settings → Tools → Tool
Servers**.

(`scripts/openwebui-mcp-command.sh` prints `Type: MCP / Streamable HTTP`
blocks instead — kept in case a future Open WebUI upgrade adds native MCP
connection support per `docs/openapi-to-mcp-migration.md`, but not usable
on this build as of 2026-08-11.)

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

See `openwebui-role-prompts.md` for the full step-by-step sequence
(register the analyst connection → create both groups → install
`sigint_operator_tool.py` for operator access → assign users), current
status, and the live confirmation that the MCP server enforces the
analyst/operator boundary server-side regardless of how Open WebUI is
configured. **Not** "scope both connections to their groups" — that was
the original plan, confirmed not to work in this Open WebUI build; see
that file's History section before assuming otherwise.

## Notes

- Start with `SIGLIERE_MCP_DRY_RUN=true` for validation.
- Flip to `false` only after ka9q-python method compatibility is verified on your host.
- If Open WebUI native MCP remains incompatible in your version, you can keep using the existing OpenAPI server path in `openapi-tools/` while this MCP service is validated.
- On this project's own host: `SIGLIERE_MCP_DRY_RUN` is `false` (production)
  as of 2026-08-11, both nodes (`rx888-hf`, `hackrf-vhf-uhf`) already
  passed live `set_frequency` tests — see
  `docs/mcp-validation-evidence.md`. That's this host's own state, not a
  new default for `.env.example`/`mcp.env.example`, which deliberately
  stay `true` for a fresh deployment that hasn't proven its own nodes yet.
