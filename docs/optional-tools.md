# Optional tools (Whisper and the native fallback tools)

Beyond the core SIGedge Status and Operator tools ([openwebui-setup.md](openwebui-setup.md)),
this repository provides five analyst capabilities: Kismet bridge, occupancy,
SigID reference, MAC vendor lookup, and Whisper transcription. The data
sources behind them (mirrors and producers) and Whisper are optional in
[INSTALL.md](../INSTALL.md); the MCP server that serves the four lookups is
standard. Each uses local mirrors or files at runtime; tool calls do not leave the host. Initial mirror
and model downloads still require network access. Occupancy and the Kismet
bridge are the exceptions worth flagging: their data comes from the live
gateway (loopback-only, still host-local), not a mirror.

**Recommended path:** the Kismet, occupancy, SigID, and MAC-vendor tools are
served by the [MCP server](#mcp-server) (standard install), which reads their
data in its own sandboxed container. Open WebUI no longer mounts that data.
The sections below for those four tools describe the **native-tool fallback**
(a tool pasted into Open WebUI that reads the data directly). Using it means
re-adding the matching `Volume=` line to `containers/open-webui.container`
and re-running `install-open-webui.sh`, and it should not be attached to the
same model as the MCP tools. Whisper has no MCP equivalent and stays native.

The four fallback tools are generated from shared logic in `sigliere_core/`;
the files in `openwebui-tools/` are the self-contained, paste-ready builds. Do
not edit them by hand. See [tool-development.md](tool-development.md).

| Tool | Native file | Data it reads | Served by |
|---|---|---|---|
| MAC Vendor Lookup | `mac_lookup_tool.py` | `/data/reference/mac-vendors` | MCP (fallback: native) |
| SigID Reference | `sigid_reference_tool.py` | `/data/reference/sigid` | MCP (fallback: native) |
| Whisper Transcription | `sigint_whisper_tool.py` | `/data/audio` (mounted in Open WebUI) | Native only |
| Occupancy | `occupancy_tool.py` | `/data/occupancy` (written by `occupancy.service`) | MCP (fallback: native) |
| Kismet Bridge | `kismet_tool.py` | `/data/kismet-bridge` (written by `kismet-bridge.service`) | MCP (fallback: native) |

## Mounts

Open WebUI mounts only `/data/audio`. Podman refuses to start a container
whose mount source is missing, so run `install-corpus-dirs.sh` first. For a
native fallback tool, add its line to `containers/open-webui.container` and
re-run the installer (same `SIGLIERE_HOSTNAME`):

```ini
Volume=/data/kismet-bridge:/data/kismet-bridge-ref:ro
Volume=/data/occupancy:/data/occupancy-ref:ro
Volume=/data/reference/sigid:/data/sigid-ref:ro
Volume=/data/reference/mac-vendors:/data/mac-vendors-ref:ro
```

Quadlet drop-ins (`open-webui.container.d/*.conf`) are not used: Podman 4.x
ignores them, and on Podman 5 a duplicate mount of the same destination fails
the container start.

## MAC Vendor Lookup

Identifies the manufacturer behind a MAC address (or searches vendors by
name) from a local mirror of the IEEE OUI/CID registry — useful for
naming devices Kismet has already seen. Never queries an external
lookup API.

1. Run `./scripts/install-mac-mirror.sh` (not `sudo` — it installs a user
   service) to populate `/data/reference/mac-vendors` and install a weekly
   `systemd --user` refresh timer. Validate with
   `./scripts/validate-mac-mirror.sh`.
2. Fallback only: add the `mac-vendors` `Volume=` line from the Mounts section and re-run `install-open-webui.sh`.
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
2. Fallback only: add the `sigid` `Volume=` line from the Mounts section and re-run `install-open-webui.sh`.
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
2. The `/data/audio` mount is already in `containers/open-webui.container`.
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
2. Fallback only: add the `occupancy` `Volume=` line from the Mounts section and re-run `install-open-webui.sh`.
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
2. Fallback only: add the `kismet-bridge` `Volume=` line from the Mounts section and re-run `install-open-webui.sh`.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/kismet_tool.py`.
4. Leave the `KISMET_BRIDGE_DB_PATH` valve at its default
   (`/data/kismet-bridge-ref/kismet_bridge.db`) — it matches the mount
   target above.
5. Attach to a model and test with `kismet_summary` first, then
   `query_wifi_devices` (by `mac`, `ssid`, `device_type`, `phy`, or
   `node_id`).

## MCP server

The MCP server is a standard component of the install, not an optional tool:
see [INSTALL.md](../INSTALL.md) step 5, [openwebui-setup.md](openwebui-setup.md#connect-the-mcp-server)
for connecting it, and [mcp-server-design.md](mcp-server-design.md) for the
design. Rotate its token as described in [operations.md](operations.md#rotate-the-mcp-token).
