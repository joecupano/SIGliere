# Sigliere

A web-accessible software-defined radio platform with a local ("sovereign")
AI layer for SIGINT. Signals captured by your own hardware become a structured,
queryable record that a **local LLM** reasons over in natural language —
what's active on the RF bands, what WiFi devices are present, and what a given
signal is likely to be — with **no cloud dependency** for the core pipeline.

Everything runs on-prem. The design principle is **local by default, cloud by
exception**: cloud LLMs, if used at all, are a deliberate opt-in for sanitized,
non-sensitive queries — never a silent dependency in the main pipeline.

This repo documents a **reproducible build** so others with comparable hardware
can stand up the same platform at their own location.

## Status

**Working end to end.** The capture → database → AI loop is closed and
reboot-durable, with three live AI data sources and calibrated RF sensors. See
[docs/build-order.md](docs/build-order.md) for the phase-by-phase build and
[docs/README.md](docs/README.md) for the full guide index.

## What it does

**Three AI data sources, each queried live by the local LLM through Open WebUI
tools (native and external OpenAPI):**

| Source | Answers | Backed by |
|---|---|---|
| **RF occupancy** | What's active on the bands, when, how often? | `radiod` HF producer (wired, running) → occupancy DB |
| **WiFi device intelligence** | What access points / clients were seen? | Kismet capture → kismetdb |
| **Signal reference** | What *is* this signal? | Local mirror of the [SIGIDwiki catalog](https://www.sigidwiki.com) |

Plus a **vision-assisted identification workflow**: a local vision model
describes an unknown signal's waterfall shape, the signal-reference tool
supplies candidate matches, and your own receiver's measured frequency
confirms — a three-way triangulation, entirely local. See
[docs/vision-signal-identification-guide.md](docs/vision-signal-identification-guide.md).

## Reference hardware

Your build will differ; this is the reference platform the docs were validated
against. **Calibration values, antennas, and receivable reference signals are
location-specific** — the guides teach how to re-derive them for your site.

| Component | Spec |
|---|---|
| Server | Dell Precision Tower 5820 |
| RAM | 64 GB |
| GPU | NVIDIA GeForce RTX 5060 Ti (16 GB) |
| HF SDR | RX-888 MkII (direct sampling) |
| VHF/UHF SDR | HackRF One (2m or 70cm, one profile at a time, via radiod), RTL-SDR (interactive only, via OpenWebRX+) |
| WiFi capture | MT7612U (Kismet) |
| Bluetooth / sub-GHz (future) | Ubertooth One |
| OS | Ubuntu 24.04 Server |

## Architecture

- **HF AI ingest** — [ka9q-radio](https://github.com/ka9q/ka9q-radio) (`radiod`)
  drives the RX-888 MkII directly, wideband-sampling HF and channelizing it
  into many simultaneous demodulated channels over IP multicast. Native
  RX-888 support; no SoapySDR layer.
- **VHF/UHF AI ingest** — [ka9q-radio](https://github.com/ka9q/ka9q-radio) (`radiod`)
  drives the HackRF directly, wideband-sampling (20 MHz) of VHF or UHF and
  channelizing it into many simultaneous demodulated channels over IP
  multicast. Native HackRF support; no SoapySDR layer.
- **HF/VHF/UHF interactive** — An RTL-SDR is dedicated for interactive use
  with OpenWebRX+ providing the web waterfall/tuning. **Not part of the
  AI path** — a `radiod`-driven ad hoc live-tasking path was built and
  fixed at the client/MCP level, but tracing revealed a `ka9q-radio`
  bug that limits a live-tasked channel to one control command per
  `radiod` restart, unfixable from this repo. Filed upstream:
  [ka9q/ka9q-radio#239](https://github.com/ka9q/ka9q-radio/issues/239)
  (drafted as `docs/ka9q-radio-upstream-issue-command-queue.md`, removed
  from the repo 2026-08-08 once actually filed — the GitHub issue is the
  living copy now, closed 2026-08-10 pending an unmerged upstream fix,
  not yet independently re-verified — see `docs/mcp-validation-evidence.md`'s
  2026-08-11 entries).
  Full evidence: [docs/mcp-validation-evidence.md](docs/mcp-validation-evidence.md).
  The `mcp-server` code and `radiod` conf built for this are kept
  in-repo (not deleted) in case `ka9q-radio` gets patched.
- **Occupancy producers** — `radiod` (continuous HF, measuring power on each
  demodulated channel) is the one running as a continuous default: installed
  as a continuous systemd `--user` service by
  `scripts/phase6-occupancy-producer.sh`, confirmed on real hardware to
  actively grow the occupancy DB from live HF traffic.
  
  **HackRF has its own `radiod` instance, selectable between band profiles**
  (`ingest/ka9q-radio/radiod@hackrf-2m.conf`, `radiod@hackrf-70cm.conf`, or
  any operator-created one — HackRF's 20 MHz instantaneous bandwidth can't
  span 2m+70cm in one capture, and it's a single-owner USB device, so only
  one profile runs at a time). `scripts/sdr-mode.sh hackrf list` shows
  what's available and which is active; `sudo scripts/sdr-mode.sh hackrf ai
  [profile]` switches to one (omit `profile` to reaffirm whichever is
  already active); `scripts/sdr-mode.sh hackrf new <name>` scaffolds a new
  profile (structure only — it does not invent channel frequencies for
  you). Whichever profile is active is read by the same generalized
  `decode/radiod_occupancy_producer.py --device hackrf`, run by
  `systemd/radiod-occupancy-hackrf.service` (installed by
  `scripts/phase6-hackrf-occupancy-producer.sh`) — the producer
  auto-detects the active profile on every sweep, so switching profiles
  doesn't require restarting it.

  HackRF driver support is confirmed working on this build (device found,
  independently cross-checked with the stock `hackrf_info` tool). A real
  config bug was found and fixed 2026-08-11: `radiod@hackrf-2m.conf`'s
  `mix-gain` key was silently ignored (not a key this `radiod` build
  recognizes — `mixer-gain` is) and `lna-gain` was never a 0-40dB value,
  despite the name (it's a boolean, passed to
  `hackrf_set_antenna_enable()`). Both fixed; see
  `radiod@hackrf-2m.conf`'s header and `docs/mcp-validation-evidence.md`
  for the full source-level trace. The five 2m channels are confirmed
  receiving the live multicast RTP audio stream and reporting real channel
  power values; the occupancy threshold remains an uncalibrated
  placeholder — a live sweep found suspiciously uniform readings across
  every channel simultaneously, cause not yet isolated (the gain bug above
  was ruled out), so don't trust ACTIVE/quiet calls from it yet.
  
  **RTL-SDR is OpenWebRX+-only** (decided after the ad hoc AI-tasking
  path below was tried and abandoned), so there is no producer writing
  VHF/UHF sightings for that device, and none is planned. See
  [docs/occupancy-guide.md](docs/occupancy-guide.md) for the full, current
  state of each producer.
- **Decode layer** — `direwolf` (APRS/AX.25), `multimon-ng` (POCSAG/FLEX/etc.),
  `ffmpeg` for archival recording. (These are also OpenWebRX+'s auto-detected
  decoders.)
- **AI layer** — Ollama + Open WebUI, GPU-accelerated locally. The occupancy
  query path is exposed by the local **OpenAPI tool server**
  (`openapi-tools/sigint_openapi_server.py`) and registered in Open WebUI as an
  OpenAPI connection. Native tools remain available in
  `openwebui-tools/` for in-process workflows. Models:
  `qwen3:14b` (reasoning + tools), `gemma3:12b` (vision), `nomic-embed-text`
  (embeddings). Setup: [docs/openwebui-setup-guide.md](docs/openwebui-setup-guide.md).
- **Control plane (MCP)** — `mcp-server/` (`sigliere_mcp_server.py`) exposes
  SDR state and radiod-driven control (frequency/mode changes) as MCP tools,
  built and validated separately from the OpenAPI query path — see
  [docs/MCP-server-design.md](docs/MCP-server-design.md) and
  [docs/mcp-validation-evidence.md](docs/mcp-validation-evidence.md). Runs as
  the `sigliere-mcp` Podman Quadlet service; Open WebUI still connects via
  OpenAPI until MCP tool support is stable in your deployed version — see
  [docs/openapi-to-mcp-migration.md](docs/openapi-to-mcp-migration.md). Live
  in production (not dry-run) on this host as of 2026-08-11. Read-only
  access is a registered OpenAPI connection; tuning access is deliberately
  **not** a connection at all — it's `openwebui-tools/sigint_operator_tool.py`,
  a native tool that checks the calling user's Open WebUI group membership in
  code, after confirming this Open WebUI build has no working way to scope a
  shared connection to a group — see
  `mcp-server/openwebui-role-prompts.md`'s History section.
- **Services** — rootless Podman Quadlet units + systemd `--user` timers;
  Caddy fronts Open WebUI for LAN/TLS access.

**GNU Radio** was used early for occupancy flowgraphs but has been **removed**:
nothing in the working build needs it (direct captures replaced it, and
OpenWebRX+ handles interactive viewing using the RTL-SDR). Flowgraph/demodulation work is a deferred advanced topic, better suited to a desktop workstation — the reference flowgraphs remain in [`decode/gnuradio-flowgraphs/`](decode/gnuradio-flowgraphs/).

## Repo layout

```
docs/               build order, guides, and architecture notes (start at docs/README.md)
scripts/            phased build + validation scripts (phase1 … phase7)
systemd/            systemd --user service/timer units
containers/         Podman Quadlet unit files (Open WebUI, Caddy, MCP server)
ingest/
  ka9q-radio/       radiod configs: RX-888 (HF), HackRF (2m/70cm), RTL-SDR (ad hoc AI tasking -- built, then abandoned, see docs/mcp-validation-evidence.md; RTL-SDR is OpenWebRX+-only now)
  openwebrx/        OpenWebRX+ profiles for HackRF/RTL-SDR
  direwolf/         APRS/AX.25 TNC configs
decode/             occupancy producers, SigMF writer, reference flowgraphs
db/                 occupancy database schema + access layer
reference/          SigID (sigidwiki) sovereign mirror
openwebui-tools/    native AI tools (occupancy, Kismet, SigID, Whisper transcription)
openapi-tools/      OpenAPI tool server for Open WebUI external-tool integration
mcp-server/         MCP control-plane server (SDR state/tuning via radiod)
protocol-security/  Kismet and related protocol/WiFi tooling
ai-ingest/          document/image/audio ingest for the RAG knowledge feature
packages/           pre-built ka9q-radio Debian packages (see packages/README.md
                     for exact commit/build flags -- not what this host's live
                     radiod instances actually run, see that file)
```

## Not yet built / deferred

Kept honest: **CW and voice callsign-tracking** (`decode/cw-decode/`,
`decode/voice-transcribe/`) are placeholders, not implemented. **Ubertooth**
(Bluetooth) and **Evil Crow RF** (sub-GHz) hardware is planned but not yet
wired into the AI layer. **GNU Radio flowgraph** work is deferred. Some
integrations are parked on upstream fixes (see the guides).

## License

AGPL-3.0 — see [LICENSE](./LICENSE). Chosen deliberately given the copyleft
stack this build orchestrates (ka9q-radio, direwolf, multimon-ng under GPL;
OpenWebRX+ under AGPL): it keeps this repo's own code consistent with that
philosophy, includes an explicit patent grant, and closes the "hosted service"
loophole plain GPL leaves open — relevant since this repo includes actual
network-facing services.

## Contributing

Issues and PRs welcome. This is a from-scratch public build intended to be
reproducible on comparable hardware. If you build it at your own site,
real-world notes on where the docs or scripts didn't match your hardware or
signal environment are especially valuable.
