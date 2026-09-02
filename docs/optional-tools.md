# Optional native tools

Beyond the core SIGedge Status and Operator tools ([openwebui-setup.md](openwebui-setup.md)),
`openwebui-tools/` ships three more native tools. All three are optional —
none are required to complete [build-order.md](build-order.md) — and each
reads from a local mirror or local files only; nothing they do leaves the
box.

| Tool | File | Needs |
|---|---|---|
| MAC Vendor Lookup | `mac_lookup_tool.py` | `/data/reference/mac-vendors` mirror (Phase 6.8) |
| SigID Reference | `sigid_reference_tool.py` | `/data/reference/sigid` mirror (Phase 6.3) |
| Whisper Transcription | `sigint_whisper_tool.py` | `/data/audio` (already created by `setup-data-dirs.sh`) |

## Mount the data in first

Each tool runs inside the Open WebUI container and only reads what's
mounted into it. `containers/open-webui.container` doesn't mount any of
these paths by default, and `install-open-webui.sh` overwrites that file on
every re-run — so add the mounts as a Quadlet drop-in rather than editing
the installed file directly, per
[openwebui-setup-details.md](openwebui-setup-details.md#L16-18):

```bash
mkdir -p ~/.config/containers/systemd/open-webui.container.d
cat > ~/.config/containers/systemd/open-webui.container.d/reference-mounts.conf <<'EOF'
[Container]
Volume=/data/reference/mac-vendors:/data/mac-vendors-ref:ro
Volume=/data/reference/sigid:/data/sigid-ref:ro
Volume=/data/audio:/data/audio:ro
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

1. Run `./scripts/phase6-mac-mirror.sh` (not `sudo` — rootless, same as
   the other Phase 6 scripts) to populate `/data/reference/mac-vendors`
   and install a weekly `systemd --user` refresh timer. Validate with
   `./scripts/phase6-mac-mirror-validate.sh`.
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

1. Run `./scripts/phase6-sigid-mirror.sh` (rootless) to populate
   `/data/reference/sigid` and install its weekly refresh timer.
   Validate with `./scripts/phase6-sigid-mirror-validate.sh`.
2. Add the `sigid` `Volume=` line from above and restart Open WebUI.
3. **Workspace → Tools → Create a new tool**, paste
   `openwebui-tools/sigid_reference_tool.py`.
4. Leave the `SIGID_METADATA_DIR` valve at its default
   (`/data/sigid-ref/metadata`) — it matches the mount target above.
5. Attach to a model and test with `lookup_signal` (e.g. `"LoRa"`) and
   `search_signals` (by keyword, by `near_frequency_hz`, or both).

## Whisper Transcription

On-demand speech-to-text (or translation to English) for a single audio
file, via `faster-whisper` on GPU — the chat-time counterpart to Phase
5's bulk/background audio ingest. Same model and GPU fallback logic as
`ai-ingest/extractors/audio.py`, different latency profile: this runs
immediately when asked, rather than on `ai-ingest.timer`'s schedule.

1. No mirror step — `/data/audio` already exists from
   `scripts/setup-data-dirs.sh`. Just place audio files there (`.wav`,
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
5. Optional: to reuse Phase 5's already-downloaded model weights instead
   of a fresh in-container download, add
   `Volume=%h/.cache/huggingface:/root/.cache/huggingface` to the same
   drop-in file.
6. Attach to a model and test with `list_audio_files` first, then
   `transcribe_audio` on one of the listed files.
