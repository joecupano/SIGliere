# Optional native tools

Beyond the core SIGedge Status and Operator tools ([openwebui-setup.md](openwebui-setup.md)),
`openwebui-tools/` ships five more native tools. All five are optional —
none are required to complete [INSTALL.md](../INSTALL.md) — and each
uses local mirrors or files at runtime; tool calls do not leave the
host. Initial mirror and model downloads still require network access.
Occupancy and the Kismet bridge are the exceptions worth flagging: their
data comes from the live gateway (loopback-only, still host-local), not a
mirror.

| Tool | File | Needs |
|---|---|---|
| MAC Vendor Lookup | `mac_lookup_tool.py` | `/data/reference/mac-vendors` mirror |
| SigID Reference | `sigid_reference_tool.py` | `/data/reference/sigid` mirror |
| Whisper Transcription | `sigint_whisper_tool.py` | `/data/audio` (already created by `install-corpus-dirs.sh`) |
| Occupancy | `occupancy_tool.py` | `/data/occupancy` (written by `occupancy.service`) |
| Kismet Bridge | `kismet_tool.py` | `/data/kismet-bridge` (written by `kismet-bridge.service`) |

## Mount the data in first

Each tool runs inside the Open WebUI container and only reads what's
mounted into it. `containers/open-webui.container` doesn't mount any of
these paths by default, and `install-open-webui.sh` overwrites that file on
every re-run — so add the mounts as a Quadlet drop-in rather than editing
the installed file directly:

```bash
mkdir -p ~/.config/containers/systemd/open-webui.container.d
cat > ~/.config/containers/systemd/open-webui.container.d/reference-mounts.conf <<'EOF'
[Container]
Volume=/data/reference/mac-vendors:/data/mac-vendors-ref:ro
Volume=/data/reference/sigid:/data/sigid-ref:ro
Volume=/data/audio:/data/audio:ro
Volume=/data/occupancy:/data/occupancy-ref:ro
Volume=/data/kismet-bridge:/data/kismet-bridge-ref:ro
EOF

systemctl --user daemon-reload
systemctl --user restart open-webui.service
```

Only add the `Volume=` lines for tools you're actually installing — each
line is independent.

## MAC Vendor Lookup

Identifies the manufacturer behind a MAC address (or searches vendors by
name) from a local mirror of the IEEE OUI/CID registry — useful for
naming devices Kismet has already seen. Never queries an external
lookup API.

1. Run `./scripts/install-mac-mirror.sh` (not `sudo` — it installs a user
   service) to populate `/data/reference/mac-vendors` and install a weekly
   `systemd --user` refresh timer. Validate with
   `./scripts/validate-mac-mirror.sh`.
2. Add the `mac-vendors` `Volume=` line from above and restart Open WebUI.
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
2. Add the `sigid` `Volume=` line from above and restart Open WebUI.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/sigid_reference_tool.py`.
4. Leave the `SIGID_METADATA_DIR` valve at its default
   (`/data/sigid-ref/metadata`) — it matches the mount target above.
5. Attach to a model and test with `lookup_signal` (e.g. `"LoRa"`) and
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
2. Add the `audio` `Volume=` line from above and restart Open WebUI.
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
   `Volume=%h/.cache/huggingface:/root/.cache/huggingface` to the same
   drop-in file.
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
2. Add the `occupancy` `Volume=` line from above and restart Open WebUI.
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
2. Add the `kismet-bridge` `Volume=` line from above and restart Open WebUI.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/kismet_tool.py`.
4. Leave the `KISMET_BRIDGE_DB_PATH` valve at its default
   (`/data/kismet-bridge-ref/kismet_bridge.db`) — it matches the mount
   target above.
5. Attach to a model and test with `kismet_summary` first, then
   `query_wifi_devices` (by `mac`, `ssid`, `device_type`, `phy`, or
   `node_id`).
