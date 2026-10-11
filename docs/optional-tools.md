# Optional native tools

Beyond the core SIGedge Status and Operator tools ([openwebui-setup.md](openwebui-setup.md)),
`openwebui-tools/` ships five more native tools. All five are optional —
none are required to complete [INSTALL.md](../INSTALL.md) — and each
uses local mirrors or files at runtime; tool calls do not leave the
host. Initial mirror and model downloads still require network access.
Occupancy and the Kismet bridge are the exceptions worth flagging: their
data comes from the live gateway (loopback-only, still host-local), not a
mirror.

The MAC, SigID, Occupancy, and Kismet tools are generated from shared logic
in `sigliere_core/`; the files in `openwebui-tools/` are the self-contained,
paste-ready builds. Do not edit them by hand. See
[tool-development.md](tool-development.md).

| Tool | File | Needs |
|---|---|---|
| MAC Vendor Lookup | `mac_lookup_tool.py` | `/data/reference/mac-vendors` mirror |
| SigID Reference | `sigid_reference_tool.py` | `/data/reference/sigid` mirror |
| Whisper Transcription | `sigint_whisper_tool.py` | `/data/audio` (already created by `install-corpus-dirs.sh`) |
| Occupancy | `occupancy_tool.py` | `/data/occupancy` (written by `occupancy.service`) |
| Kismet Bridge | `kismet_tool.py` | `/data/kismet-bridge` (written by `kismet-bridge.service`) |

## Mount the data in first

Each tool runs inside the Open WebUI container and only reads what's
mounted into it. `containers/open-webui.container` mounts each data
directory read-only (`:ro`), and `install-open-webui.sh` installs it. Podman
refuses to start the container if a source directory is missing, so run
`install-corpus-dirs.sh` first, or delete the `Volume=` line for any
optional tool you are not installing.

Quadlet drop-ins (`open-webui.container.d/*.conf`) are not used for these
mounts: Podman 4.x ignores them, and on Podman 5 a duplicate mount of the same
destination fails the container start.

After changing mounts, re-run the installer so the unit is regenerated:

```bash
SIGLIERE_HOSTNAME=<host-or-ip> ./scripts/install-open-webui.sh
```

## MAC Vendor Lookup

Identifies the manufacturer behind a MAC address (or searches vendors by
name) from a local mirror of the IEEE OUI/CID registry — useful for
naming devices Kismet has already seen. Never queries an external
lookup API.

1. Run `./scripts/install-mac-mirror.sh` (not `sudo` — it installs a user
   service) to populate `/data/reference/mac-vendors` and install a weekly
   `systemd --user` refresh timer. Validate with
   `./scripts/validate-mac-mirror.sh`.
2. Confirm the `mac-vendors` mount is active: `podman inspect open-webui --format '{{range .Mounts}}{{.Destination}} {{end}}'`.
3. In Open WebUI, **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/mac_lookup_tool.py`.
4. Leave the `MAC_VENDOR_DB_PATH` valve at its default
   (`/data/mac-vendors-ref/mac-vendors.json`) — it already matches the
   mount target above.
5. Attach the tool to a model and test with `lookup_mac_vendor` (e.g. a
   MAC prefix like `AA:BB:CC`) and `search_mac_vendors` (e.g. a vendor
   name).

## SigID Reference

Looks up signals by name, keyword, or frequency in a local mirror of the
SigID (sigidwiki) catalog — the reference layer that identifies *what a
signal is*, separate from your own capture/observation data.

1. Run `./scripts/install-sigid-mirror.sh` (rootless) to populate
   `/data/reference/sigid` and install its weekly refresh timer.
   Validate with `./scripts/validate-sigid-mirror.sh`.
2. Confirm the `sigid` mount is active: `podman inspect open-webui --format '{{range .Mounts}}{{.Destination}} {{end}}'`.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/sigid_reference_tool.py`.
4. Leave the `SIGID_METADATA_DIR` valve at its default
   (`/data/sigid-ref/metadata`) — it matches the mount target above.
5. Attach to a model and test with `lookup_signal` (e.g. `"OTH Radar"`) and
   `search_signals` (by keyword, by `near_frequency_hz`, or both).

## Whisper Transcription

On-demand speech-to-text or English translation for a single audio file via
`faster-whisper`. It is the chat-time counterpart to the scheduled bulk audio
ingest pipeline and uses the same model and GPU fallback logic as
`ai-ingest/extractors/audio.py`. Unlike the scheduled pipeline, this tool runs
immediately when asked.

1. No mirror step — `/data/audio` already exists from
   `scripts/install-corpus-dirs.sh`. Just place audio files there (`.wav`,
   `.mp3`, `.m4a`, `.flac`, `.ogg`, `.opus`).
2. Confirm the `audio` mount is active: `podman inspect open-webui --format '{{range .Mounts}}{{.Destination}} {{end}}'`.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/sigint_whisper_tool.py`. Open WebUI reads the file's
   `requirements: faster-whisper>=1.0.0` line and installs it into the
   container automatically on load. If that install fails, do it by hand:
   ```bash
   podman exec -u root open-webui pip install "faster-whisper>=1.0.0"
   ```
4. Leave `AUDIO_ROOT` at its default (`/data/audio`) — it matches the
   mount target above. `MODEL_SIZE` defaults to `medium`; `DEVICE`
   defaults to `auto` (GPU with a clean CPU fallback).
5. Optional: to reuse the AI ingest pipeline's downloaded model weights instead
   of a fresh in-container download, add
   `Volume=%h/.cache/huggingface:/root/.cache/huggingface` to
   `containers/open-webui.container` and re-run
   `install-open-webui.sh`.
6. Attach to a model and test with `list_audio_files` first, then
   `transcribe_audio` on one of the listed files.

## Occupancy

Logs which frequencies SIGedge has actively demodulated — a signals-heard
record, not a signal identification. See
[occupancy-guide.md](occupancy-guide.md) for the full design, including why
it's built as a gateway poller rather than a direct SDR capture. Requires
the gateway already installed (`./scripts/install-sigedge-gateway.sh`).

1. Run `./scripts/install-occupancy.sh` (not `sudo`) to install the
   `occupancy` venv and start `occupancy.service`, a persistent poller of
   the gateway's `/status` endpoint. Validate with
   `./scripts/validate-occupancy.sh`.
2. Confirm the `occupancy` mount is active: `podman inspect open-webui --format '{{range .Mounts}}{{.Destination}} {{end}}'`.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/occupancy_tool.py`.
4. Leave the `OCCUPANCY_DB_PATH` valve at its default
   (`/data/occupancy-ref/occupancy.db`) — it matches the mount target above.
5. Attach to a model and test with `occupancy_summary` first, then
   `query_occupancy` (e.g. `near_frequency_hz` for a known SIGedge node
   frequency) and `occupancy_sightings` (by `signal_key` from a
   `query_occupancy` result).

## Kismet Bridge

Mirrors which WiFi, Bluetooth, and ADS-B devices a standalone Kismet
server has seen — device presence, not frequency activity (that's
Occupancy, above) and not signal identification (that's SigID Reference).
See [kismet-bridge-guide.md](kismet-bridge-guide.md) for the full design,
including why it's a gateway poller rather than a mounted `.kismet` file.
Requires the gateway already installed
(`./scripts/install-sigedge-gateway.sh`), plus at least one node with
`kismet_host` set and a matching API key in
`SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON` (see
[gateway/README.md](../gateway/README.md#kismet-bridge)).

1. Run `./scripts/install-kismet-bridge.sh` (not `sudo`) to install the
   `kismet-bridge` venv and start `kismet-bridge.service`, a persistent
   poller of the gateway's `/kismet/summary/{node}` and
   `/kismet/devices/{node}` endpoints. Validate with
   `./scripts/validate-kismet-bridge.sh`.
2. Confirm the `kismet-bridge` mount is active: `podman inspect open-webui --format '{{range .Mounts}}{{.Destination}} {{end}}'`.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/kismet_tool.py`.
4. Leave the `KISMET_BRIDGE_DB_PATH` valve at its default
   (`/data/kismet-bridge-ref/kismet_bridge.db`) — it matches the mount
   target above.
5. Attach to a model and test with `kismet_summary` first, then
   `query_wifi_devices` (by `mac`, `ssid`, `device_type`, `phy`, or
   `node_id`).

## MCP server (optional)

A read-only MCP service that serves the Kismet, occupancy, SigID, and MAC
tools from a separate sandboxed container instead of inside Open WebUI. See
[mcp-server-design.md](mcp-server-design.md) for the design and migration
plan. It is optional and runs alongside the native tools above.

1. Prerequisites: the data directories exist (`install-corpus-dirs.sh`).
2. `./scripts/install-sigliere-mcp.sh` (not `sudo`) builds the image, creates
   `~/.config/sigliere/mcp.env` (mode 0600, only the MCP token), and starts
   `sigliere-mcp.service` on `127.0.0.1:8150`.
3. The private Caddy router needs its `/mcp` route. It is generated by
   `install-open-webui.sh`; re-run it (same `SIGLIERE_HOSTNAME`) if the
   installer says the route is not answering.
4. `./scripts/validate-sigliere-mcp.sh` checks authentication, the exact tool
   list, one call per tool, and the container's privileges.
5. In Open WebUI as admin: **Tools → Integrations**, add a connection of type
   **MCP (Streamable HTTP)**. URL `http://127.0.0.1:8180/mcp/`, auth
   **Bearer**, the `SIGLIERE_MCP_TOKEN` from `mcp.env`, and **set the
   Connection ID field to `mcp` explicitly when you create it**. If the ID is
   left blank Open WebUI generates a UUID, and it cannot be changed by editing
   the display name afterwards (delete and recreate the connection instead).
   Open WebUI prefixes tool names with the ID (`mcp_query_wifi_devices`). Use
   a short, neutral ID: with `qwen3:14b` the ID `sigliere` made the model skip
   a tool call on one question every time, while `mcp` did not (see
   [mcp-server-design.md](mcp-server-design.md#14-phase-2-results)).
   An empty access list means admin-only; grant a group if analysts need it.
   Set the function filter to the nine tool names (comma-separated). Leave direct connections disabled.
6. Attach it to a test model that does not also have the native copies.

The token is rotated by deleting `mcp.env`, re-running the installer, and
updating the Open WebUI connection.
