# Operations

This guide covers changes made after the core installation. Run commands as
the rootless Podman user unless a command explicitly uses `sudo`.

## Enable or disable live gateway control

The gateway starts in dry-run mode. Before enabling live control, confirm that
`./scripts/validate-tiered.sh` passes, live SIGedge status is visible, and the
Open WebUI Operator-group check rejects an unauthorized account.

Edit `~/.config/sigliere/gateway.env` and change:

```text
SIGLIERE_GATEWAY_DRY_RUN=true
```

to:

```text
SIGLIERE_GATEWAY_DRY_RUN=false
```

Then restart and verify the gateway:

```bash
chmod 600 ~/.config/sigliere/gateway.env
systemctl --user restart sigliere-gateway.service
./scripts/validate-tiered.sh
```

Request one authorized tune from Open WebUI and confirm that the response says
`"dry_run": false` and `"status": "applied"`. To roll back immediately, set
`SIGLIERE_GATEWAY_DRY_RUN=true`, restart the service, and repeat the validation.

## Rotate gateway tokens

Generate two independent tokens with `openssl rand -hex 32`. Replace both keys
in `SIGLIERE_GATEWAY_TOKENS_JSON` inside
`~/.config/sigliere/gateway.env`, preserving this shape:

```text
SIGLIERE_GATEWAY_TOKENS_JSON={"new-analyst-token":"analyst","new-operator-token":"operator"}
```

Apply mode 0600, restart `sigliere-gateway.service`, and update the matching
Open WebUI tool valves. The old tokens stop working after the restart. Run
`./scripts/validate-tiered.sh`, then test the analyst and operator tools.

Never commit or paste real tokens into repository files or logs.

## Rotate the MCP token

`~/.config/sigliere/mcp.env` holds only `SIGLIERE_MCP_TOKEN` (the MCP server
never holds a gateway token). To rotate it, delete the file and re-run
`./scripts/install-sigliere-mcp.sh`, which generates a new token and restarts
the service. Then, in Open WebUI, **Admin Panel → Settings → Integrations**,
edit the `mcp` connection and paste the new token (the Connection ID stays
`mcp`). The old token stops working at the restart. Run
`./scripts/validate-sigliere-mcp.sh` and ask one MCP-backed question in chat.

## Rotate Kismet bridge API keys

Per-node Kismet API keys in `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON`
(`~/.config/sigliere/gateway.env`) are independent of the gateway's own
analyst/operator tokens above — see
[gateway/README.md](../gateway/README.md#kismet-bridge). To rotate one,
generate a new key against that node's Kismet instance
(`/auth/apikey/generate.cmd`, `readonly` role), replace the entry for that
`node_id` in `SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON`, restart
`sigliere-gateway.service`, then revoke the old key in Kismet. The old key
stops working for the gateway immediately on restart regardless of
revocation, since the gateway never caches a session — revoking it in
Kismet closes the window where it could still be used directly against
Kismet's own REST API.

## Back up persistent state

Stop the user services before a consistent backup:

```bash
systemctl --user stop caddy.service open-webui.service sigliere-mcp.service sigliere-gateway.service occupancy.service kismet-bridge.service
```

Back up these items to encrypted storage:

- `open-webui-state`: accounts, configuration, uploads, and vector data.
- `caddy-data` and `caddy-config`: the internal CA and Caddy runtime state.
- `~/.config/sigliere/gateway.env`: gateway credentials and dry-run setting.
- `~/.config/sigliere/mcp.env`: the MCP server token, if installed.
- `~/.config/containers/systemd/`: installed Quadlets, Caddy configuration,
  and certificates.
- `/data/models`, `/data/corpus`, `/data/reference`, `/data/imagery`,
  `/data/audio`, `/data/occupancy`, and `/data/kismet-bridge`, according to
  local retention requirements.

Inspect volume locations with `podman volume inspect` and use the host backup
system to capture them. Restart the services afterward:

```bash
systemctl --user start sigliere-gateway.service sigliere-mcp.service open-webui.service caddy.service
./scripts/validate-tiered.sh
```

If occupancy is installed, also restart it (it depends on the gateway being
up first): `systemctl --user start occupancy.service`.

Test restoration on a non-production host. Do not overwrite a running volume.

## Recover the Caddy internal CA

The public root certificate can be exported again while the original
`caddy-data` volume exists:

```bash
podman cp caddy:/data/caddy/pki/authorities/local/root.crt ./sigliere-root-ca.crt
```

If `caddy-data` is lost, Caddy creates a new internal CA. Export the new root
and replace the trusted certificate on every client. Restoring only an old
public root certificate does not restore its private signing key.

Deployments using an operator-provided certificate should restore the
`caddy-certs` directory and rerun `./scripts/install-open-webui.sh` with the
certificate, key, and original `SIGLIERE_HOSTNAME`.

## Upgrade safely

1. Record the current repository revision and back up persistent state.
2. Review changes to container image tags, environment files, node contracts,
   and Quadlets.
3. Re-run the relevant installer. The gateway installer preserves an existing
   `gateway.env`; the Open WebUI installer replaces the base Quadlets
   (including the data mounts in `open-webui.container`).
4. Reload user units, restart affected services, and run the relevant
   validators.
5. Keep gateway control in dry-run through any gateway or KA9Q client upgrade
   until live status and authorization have been reverified.

Caddy follows its tagged container update policy.

### Upgrade Open WebUI

Open WebUI is pinned to a release tag in `containers/open-webui.container`, so
upgrading is an explicit repository change. `AutoUpdate=registry` does not
move a pinned tag.

1. Read the release notes. Open WebUI migrates its database forward on
   startup and older versions generally cannot read the newer schema, so the
   backup below is the only rollback path.
2. Back up the state volume:
   ```bash
   systemctl --user stop open-webui.service
   podman volume export open-webui-state -o ~/backups/open-webui-state-$(date +%F).tar
   ```
3. Change the `Image=` tag in `containers/open-webui.container`, then
   `podman pull` the new image.
4. Reinstall with the same hostname (and certificate, if one was supplied) as
   the original install, since the Caddyfile is regenerated:
   ```bash
   SIGLIERE_HOSTNAME=<host-or-ip> ./scripts/install-open-webui.sh
   ```
5. Verify: `curl -s http://127.0.0.1:8080/api/version`, then
   `SIGLIERE_HOSTNAME=<host-or-ip> ./scripts/validate-tiered.sh`, then run one
   query through each tool (native and MCP) in the UI.

To roll back, restore the old tag and import the exported volume
(`podman volume import`) before starting the service; never import over a
running volume.

### Updating a native tool after a rebuild

After changing `sigliere_core/` or `openwebui-tools/src/`, run
`python3 scripts/build-owui-tools.py`, then re-paste the regenerated file into
**Workspace → Tools**. Existing valve settings are kept when you edit a tool
in place.
