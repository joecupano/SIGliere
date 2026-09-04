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

## Back up persistent state

Stop the user services before a consistent backup:

```bash
systemctl --user stop caddy.service open-webui.service sigliere-gateway.service occupancy.service
```

Back up these items to encrypted storage:

- `open-webui-state`: accounts, configuration, uploads, and vector data.
- `caddy-data` and `caddy-config`: the internal CA and Caddy runtime state.
- `~/.config/sigliere/gateway.env`: gateway credentials and dry-run setting.
- `~/.config/containers/systemd/`: installed Quadlets, Caddy configuration,
  certificates, and optional drop-ins.
- `/data/models`, `/data/corpus`, `/data/reference`, `/data/imagery`,
  `/data/audio`, and `/data/occupancy`, according to local retention
  requirements.

Inspect volume locations with `podman volume inspect` and use the host backup
system to capture them. Restart the services afterward:

```bash
systemctl --user start sigliere-gateway.service open-webui.service caddy.service
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
   `gateway.env`; the Open WebUI installer replaces base Quadlets but leaves
   `.container.d` drop-ins intact.
4. Reload user units, restart affected services, and run the relevant
   validators.
5. Keep gateway control in dry-run through any gateway or KA9Q client upgrade
   until live status and authorization have been reverified.

Open WebUI is pinned to the version in `containers/open-webui.container`;
upgrading it requires an explicit repository change. Caddy follows its tagged
container update policy.
