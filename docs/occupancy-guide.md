# Understanding and Using Occupancy

A standalone reference for the occupancy capability in this build: what it
means, why it's shaped the way it is, and how to use it. Occupancy was
carried over from an earlier project,
[sovereign-sigint](https://github.com/joecupano/sovereign-sigint) — its
`docs/occupancy-guide.md` covers the original design in full; this document
covers what's the same, what had to change to fit SIGliere's tier boundary,
and why.

## What "Occupancy" Means

Standard RF/spectrum-management terminology, unchanged from the original
project — the question occupancy answers is narrow and specific: **was a
given frequency in use, over what time window.** This is deliberately
**not** the same question as "what is this signal" — identification is a
separate, optional layer ([SigID Reference](optional-tools.md#sigid-reference))
that can sit on top of an occupancy record.

## Why This Isn't a Direct Port

sovereign-sigint's occupancy producers read raw IQ or demodulator power
directly off an SDR on the same host, with a dBFS threshold hand-calibrated
per device and antenna. None of that is legal in SIGliere's architecture.
[architecture.md](architecture.md) is explicit that SIGliere must not read
SIGedge radiod configuration, invoke SIGedge systemd units, contain receiver
models or gain settings, or mount collection databases or capture
directories — SIGedge owns the entire collection tier; SIGliere's only
lawful window into it is the authenticated gateway.

That changes what a "sighting" can be. The gateway's `/status` endpoint
(`gateway/src/sigedge_gateway.py`) reflects `ka9q-python`'s
`ChannelInfo` for each active KA9Q channel: `ssrc`, `preset` (mode),
`sample_rate`, `frequency`, `snr` — no raw samples, no dBFS, no
antenna/gain knowledge. So occupancy here asks a different but equally
real question: **does SIGedge currently have a demodulator running on
this frequency.** A channel only exists in KA9Q status because something
— an always-on node configuration, or a prior operator tune through this
same gateway — asked radiod to run one there. A channel's presence in a
poll *is* an occupancy answer ("in use over this window"), not a proxy
standing in for a hardware reading SIGliere isn't allowed to take.

One direct consequence: **there is no per-site calibration step here.**
The original project's whole "Calibration — Why It Matters More Than It
Sounds" section doesn't apply — this producer never sees the raw samples a
threshold would apply to. `snr` still rides along for every sighting
(stored in `metadata_json`), and an optional `--min-snr-db` squelch-like
filter is available for sites that want one, but it is not a default gate.

## What's Built

**Schema** (`occupancy/occupancy_schema.sql`) — the same Kismet-derived
`signals`/`sightings` split as the original project, ported essentially
unchanged (see the schema file's own header for the full lineage):

| Table | Role | Kismet analog |
|---|---|---|
| `schema_version` | Tracks schema evolution | — |
| `signals` | Aggregate per `(frequency_hz bin, mode)` — `first_seen`, `last_seen`, `total_sightings`, optional `candidate_sigid` link into the SigID mirror | `DEVICES` |
| `sightings` | One row per poll where a channel was seen — exact frequency, source node, mode, SNR/SSRC/sample-rate in `metadata_json` | `PACKETS` |

Same aggregation substitute as the original project: RF signals don't carry
a durable identifier the way a WiFi/BT device's MAC address does, so
`signals` aggregates on frequency (binned) + mode instead. `FREQUENCY_BIN_HZ`
(1000 Hz) is carried over as the same honestly-flagged placeholder the
original project shipped — reasonable for narrowband HF/VHF/UHF, untested
at the extremes (tightly-packed HF digital channels, wide channels like
WiFi). See `occupancy/occupancy_db.py`'s own comment before tuning it.

**Access layer** (`occupancy/occupancy_db.py`) — zero dependencies beyond
the standard library, same reasoning as the original: importable from the
producer's own venv and, via plain `sqlite3` in the query tool below, from
inside the Open WebUI container with no cross-environment bridging.
`record_sighting()` is the single write path; `query_signals()` and
`summary()` are read-side additions the original project didn't need (its
Open WebUI tool queried the database directly with hand-rolled SQL).

**Producer** (`occupancy/occupancy_producer.py`) — polls the gateway's
`/status` (or `/status/<node_id>` when `--node` is given) on an interval
(`--interval-sec`, default 30s), authenticating with the analyst bearer
token from `~/.config/sigliere/gateway.env` — the same file
`scripts/install-sigedge-gateway.sh` generates. For every channel reported
as reachable, it calls `record_sighting()` with the channel's frequency,
preset (mode), and SNR/SSRC/sample-rate/multicast-address in
`metadata_json`. `--once` runs a single poll and exits, for validation or
manual runs; the installed service runs continuously.

**Open WebUI tool** (`openwebui-tools/occupancy_tool.py`) — reads
`occupancy.db` directly with plain `sqlite3` (no import of
`occupancy_db.py`; self-contained like every other native tool here, so it
pastes straight into Workspace → Tools with no repo checkout inside the
container). Three tools: `query_occupancy` (aggregate signals by
frequency/mode/recency), `occupancy_sightings` (raw detection events for one
signal_key), `occupancy_summary` (database-wide counts). See
[optional-tools.md](optional-tools.md#occupancy) for deployment.

## Install

```bash
./scripts/install-occupancy.sh
./scripts/validate-occupancy.sh
```

Requires the gateway already installed
(`./scripts/install-sigedge-gateway.sh`) — the producer authenticates with
its analyst token. Installs a persistent `systemd --user` service
(`occupancy.service`), not a timer — occupancy needs to catch activity on
the order of a poll interval, not the weekly-refresh shape the SigID/MAC
mirrors use, so it runs continuously rather than firing periodically from
cold.

## Honest Current Limitations

- **`FREQUENCY_BIN_HZ` remains an untested placeholder**, unchanged from
  the original project — see above.
- **Occupancy only sees what the gateway reports as an active channel.** A
  frequency SIGedge never tuned a demodulator to — even one with a strong
  signal on it — produces no sighting. This is not a passive wideband
  scanner; it reflects operator/config-driven channel activity only.
- **No adaptive detection, and deliberately no threshold to tune.** Unlike
  the original project's fixed-but-calibrated dBFS thresholds, there is
  nothing here to calibrate — `snr` is reported by radiod as-is and stored,
  not gated by default.
- **Single lawful source.** The original project had multiple producer
  shapes (radiod, HackRF/RTL-SDR key-freq scans, an unbuilt OpenWebRX+/MQTT
  path). SIGliere has exactly one — the gateway — because that's the only
  path the tier boundary allows.

## See Also

- [architecture.md](architecture.md) — the tier boundary this design
  works within
- [gateway/README.md](../gateway/README.md) — the `/status` endpoint this
  producer polls
- [optional-tools.md](optional-tools.md#occupancy) — deployment as a
  native Open WebUI tool
- `occupancy/occupancy_schema.sql`, `occupancy/occupancy_db.py`,
  `occupancy/occupancy_producer.py` — the implementation
- The original project's own
  [`docs/occupancy-guide.md`](https://github.com/joecupano/sovereign-sigint/blob/main/docs/occupancy-guide.md)
  — the full design discussion this build's schema and access layer were
  ported from, including the Kismet DEVICES/PACKETS reasoning not repeated
  here
