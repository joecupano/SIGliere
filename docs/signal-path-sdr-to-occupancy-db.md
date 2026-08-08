# Signal Path: RX-888 / HackRF → Occupancy Database

A stage-by-stage technical trace of exactly what happens to RF energy
hitting the RX-888 MkII or the HackRF One, from antenna to a row in
`db/occupancy.db`. Every stage below names the actual script, config
file, or systemd unit responsible, with the real parameters this build
runs. Where the two SDRs' paths diverge, both are covered in parallel.

**Scope:** this document stops at the database write. For how the local
LLM subsequently reads `occupancy.db` and answers natural-language
questions, see [db-to-ai-query-path.md](db-to-ai-query-path.md). For the
concept/schema rationale behind `signals`/`sightings`, see
[occupancy-guide.md](occupancy-guide.md) — this document is the
mechanical "how," that one is the design "why."

## Zero — precondition: single-owner USB arbitration

Before any of the pipeline below can run, each SDR must actually be
*owned* by its AI-path consumer (`radiod`) rather than by OpenWebRX+.
Every SDR in this build is a single-owner USB device — exactly one
process can hold it open. This is enforced, not just documented:

- **RX-888:** `scripts/rx888-mode.sh {ai|interactive|status}` (also
  reachable via `sudo scripts/sdr-mode.sh rx888 ...`). `ai` mode stops
  `openwebrx.service`, polls for the USB fd to actually release
  (`wait_for_rx888_release()` — a bare `sleep` was proven insufficient;
  a live failure hit `LIBUSB_ERROR_BUSY` because the kernel hadn't
  finished tearing down the handle), then starts `radiod@rx888-hf` and
  the `radiod-occupancy.service` producer together.
- **HackRF:** `sudo scripts/sdr-mode.sh hackrf {ai|interactive|status}`.
  `ai` mode is two systemd layers toggled together: the system-level
  `radiod@hackrf-2m` instance (owns the USB device) and the `--user`
  `radiod-occupancy-hackrf.service` (reads its channels). Needs `sudo`
  because the radiod layer is a system service, unlike the old
  `--user`-only scan producer it replaced.

If the wrong owner holds the device, every stage downstream still
*runs* — it just reads silence. That is treated as correct behavior
("nothing to measure"), not an error condition, throughout this chain.

## Stage 1 — RF front end (hardware)

| | RX-888 MkII | HackRF One |
|---|---|---|
| Coverage in this build | HF, direct sampling, 0–30 MHz (64.8 MSPS mode) | VHF, 2m band only (144.39–146.52 MHz) |
| Sample rate | `samprate = 64800000` in `[rx888]` (129.6 MSPS mode available, commented out, for 0–54 MHz incl. 6m — needs more CPU headroom, not enabled here) | `samprate = 8000000` in `[hackrf]` — the 2.13 MHz 2m span fits comfortably under HackRF's 20 Msps ceiling; no need to run near the top of its range |
| Gain | `gain = 10`, `gainmode = high` — VGA-based front end, tuned against local noise floor, not a fixed LNA | `lna-gain = 40`, `mix-gain = 24` — carried over from the retired scan-based producer's calibration with the Comet GP-1 antenna |
| Physical connection requirement | Native USB3 (blue port), not through a hub — at 64.8+ MSPS there's no margin for a flaky link | USB2/3, single-owner like every device in this build |
| Firmware | `SDDC_FX3.img`, loaded onto the device at attach time by radiod | N/A (HackRF firmware is resident) |

Both devices are driven **directly by `radiod`** — no SoapySDR
abstraction layer, no intermediate `rx888d` process. RX-888 MkII
support and HackRF support are both compiled into `radiod` itself (as
of the ka9q-radio releases this build targets); `hardware = rx888` /
`hardware = hackrf` in each config's `[global]` section selects the
driver.

**Known caveat (HackRF only):** whether a given `radiod` build actually
exposes a working HackRF handler is *build-dependent* — the project's
own upstream docs disagree on whether HackRF support is delivered or
still forthcoming. `scripts/phase6-hackrf-occupancy-producer.sh`
therefore performs a real go/no-go gate (`radiod <conf>` dry-run load,
watching for a hardware-driver rejection) before installing anything
downstream — see Stage 5.

## Stage 2 — `radiod` (ka9q-radio): wideband capture → channelization

`radiod` is the one process actually touching the SDR hardware. It
wideband-samples the full front-end bandwidth once, then
**simultaneously demodulates many independent channels** out of that
one capture — the entire point of ka9q-radio over a conventional
single-channel SDR app. Each channel is defined as a `[section]` in a
device-specific config file, is demodulated continuously, and is
published as its own PCM audio RTP multicast stream, addressed by an
mDNS (`.local`) name.

Two independent `radiod` instances run on this build — one per device,
since `radiod` supports multiple simultaneous instances but each owns
exactly one front end:

### `ingest/ka9q-radio/radiod@rx888-hf.conf` — instance `rx888-hf`

- `status = rx888-hf-status.local` — the mDNS name other tools (this
  producer, `control`, `monitor`) use to find/command this instance.
- ~17 channels defined: 4 WWV time-standard beacons (2.5/5/10/15 MHz,
  AM), ham voice/CW segments across 80m–10m (LSB/USB/CW), two FT8
  digital slots (40m/20m, demodulated as USB into an audio stream for
  a downstream decoder, not itself decoding FT8), a placeholder 2m-APRS
  channel (outside RX-888 HF coverage — noted in-file as belonging to
  the VHF chain instead), and one `[wideband-iq]` raw-IQ tap at 10 MHz
  center / 192 kHz samprate for future spectral feature extraction.
- `ttl = 0` — multicast traffic stays host-local (loopback/local
  switch); nothing leaves the box.
- Each `[channel]` section has its own `data = <name>.local` — its own
  mDNS-addressed multicast stream — so a downstream consumer subscribes
  to exactly the channel it wants without parsing SSRCs.

### `ingest/ka9q-radio/radiod@hackrf-2m.conf` — instance `hackrf-2m`

- `status = hackrf-2m-status.local`.
- 5 channels, all FM, all 15 kHz bandwidth, covering the 2m
  key-frequency list ported directly from the retired
  `vhf_uhf_key_freq_producer.py`: `2m-aprs` (144.390), `2m-144900`
  (144.900), `2m-145100` (145.100), `2m-iss-145825` (145.825, ISS
  packet), `2m-calling-146520` (146.520, national calling frequency).
- 70cm is **deliberately out of scope** for this config — HackRF's 20
  MHz instantaneous bandwidth can't span both 2m and 70cm at once
  (they're ~290 MHz apart), and single-owner USB means one `radiod`
  instance runs at a time. A parallel `radiod@hackrf-70cm.conf` exists
  in the repo but is not the active instance.

Both configs are validated with `radiod -I <path>` before being
trusted (a config/hardware-driver error surfaces there, not silently
downstream).

**Where the config actually loads from:** the install scripts copy
each `.conf` from `ingest/ka9q-radio/` in the repo to `/etc/radio/` on
the host, and `systemctl enable --now radiod@<instance>` runs it from
there. The repo copy and `/etc/radio/`'s copy can drift if one is
edited without the other being resynced — worth knowing since Stage 4
below parses the **repo** copy, not `/etc/radio`'s, for its channel
list.

## Stage 3 — RTP/PCM multicast transport

Every non-IQ channel's output is a **live RTP stream over IP
multicast**, one packet stream per channel, on multicast port **5004**
(`RADIOD_MULTICAST_PORT` in the producer). Each RTP packet is a
standard 12-byte RTP header followed by a payload of **16-bit signed
little-endian mono PCM samples** — this is the wire format every
producer in Stage 4 decodes directly.

This is a deliberate, verified interface choice, documented in the
producer's own header:

> radiod does NOT (in this build's config) publish a resolvable
> wideband IQ stream [for the non-IQ channels], and its status-metadata
> tools (`powers`/`metadump`) did not yield parseable per-channel
> levels in testing. The interface that IS proven to work is reading
> the raw multicast RTP/PCM stream directly.

An earlier attempt used the `pcmrecord` CLI wrapper to capture each
channel to a WAV file; it did not reliably yield data in this
environment even when the multicast packets were visibly present on
the host. The current producer bypasses `pcmrecord` and joins the
multicast group itself with a raw Python socket (see Stage 4).

## Stage 4 — the occupancy producer: `decode/radiod_occupancy_producer.py`

This is the process that turns a live multicast stream into a decision
("this channel is occupied right now") and a database write. One
producer process runs per device, selected by `--device {rx888|hackrf|rtlsdr}`,
via `DEVICE_PROFILES` (`decode/radiod_occupancy_producer.py:102`):

| Profile | Config parsed | `source_type` | `source_device` | Threshold | Calibrated? |
|---|---|---|---|---|---|
| `rx888` | `ingest/ka9q-radio/radiod@rx888-hf.conf` | `radiod` | `rx888-hf` | **-30.0 dBFS** | **Yes** — against the demodulator's own ~-33 dBFS residual floor |
| `hackrf` | `ingest/ka9q-radio/radiod@hackrf-2m.conf` | `radiod-hackrf` | `hackrf-one` | -30.0 dBFS | No — placeholder, field calibration pending |
| `rtlsdr` | `ingest/ka9q-radio/radiod@rtlsdr-vhf.conf` | `radiod-rtlsdr` | `rtl-sdr` | -30.0 dBFS | No — no active occupancy role for RTL-SDR currently (see [occupancy-guide.md](occupancy-guide.md)) |

### 4a — parsing the channel list (`parse_channels()`)

Reads the target `.conf` file as text, splits on `\n[` section
headers, and for every section except `global`/`rx888`, regex-extracts
`freq`, `data` (the multicast stream name), and `mode`. Channels with
`mode = iq` are skipped outright — RMS-on-audio is meaningless for raw
IQ, so `[wideband-iq]` in the RX-888 config is parsed but never swept.

**Subtlety worth knowing:** if a channel section omits `mode =`
entirely, the parser defaults to `"usb"` — it does **not** inherit the
config's `[global] mode = ...` default the way `radiod` itself does.
Every channel currently defined in both shipped configs sets `mode`
explicitly, so this hasn't bitten in practice, but a new channel added
without an explicit mode would silently default to `usb` in the
producer even if the `radiod` instance demodulates it as something
else.

### 4b — reading a channel's live power (`measure_channel_dbfs()`)

For each parsed channel, once per sweep:

1. Resolve the channel's mDNS `data` name to an IPv4 multicast address
   (`socket.gethostbyname`).
2. Pick the local interface to join on — `RADIOD_MULTICAST_IFACE` env
   var if set, else the first non-loopback IPv4-bearing interface.
3. Open a raw UDP socket, `IP_ADD_MEMBERSHIP` to join the multicast
   group on port 5004, and read for `--window` seconds (default
   **2.0s**) or until ≥4096 bytes accumulate, whichever comes first.
4. `_extract_pcm_s16()` walks the accumulated bytes as a sequence of
   RTP packets, strips each 12-byte header, and unpacks the remaining
   payload as `<Nh>` (little-endian signed 16-bit) samples.
5. Compute RMS over all extracted samples, convert to dBFS:
   `20 * log10(rms / 32768.0)`. Fewer than 64 raw bytes captured (no
   data — stream silent or radiod not actually publishing it) returns
   `None` rather than a bogus dBFS reading.

### 4c — the sweep and the decision (`run_once()`)

For each channel: if `dbfs is None`, skip it (nothing to measure — the
correct response when the owning `radiod` instance isn't running). If
`dbfs >= threshold_dbfs`, the channel is **ACTIVE** and
`db.record_sighting()` is called (Stage 5) with:

- `frequency_hz` — the channel's configured center frequency (exact,
  not the DB's binned aggregate value)
- `source_type` / `source_device` — from the device profile
- `mode` — parsed from the channel section
- `metadata_json` — `{"channel": "<name>", "power_dbfs": <measured>, "threshold_dbfs": <used>}`

Otherwise the channel is logged as `quiet` (in `--verbose` output) and
nothing is written — quiet channels do not generate DB rows.

### 4d — the loop

`main()` resolves the device profile, warns loudly if that profile
isn't `calibrated` (HackRF and RTL-SDR both currently trigger this),
opens `OccupancyDB(db_path)`, then loops: sweep all channels
(`run_once`), print `N/total channels active`, sleep the remainder of
`--interval` (default **60s**) before the next sweep. `--once` runs a
single sweep and exits — used for manual calibration runs.

## Stage 5 — writing to the database: `db/occupancy_db.py`

Every producer, regardless of device, calls the **same single write
path**: `OccupancyDB.record_sighting()`. This is deliberate — the
schema and access layer make no assumption about which capture tool is
calling.

1. **`make_signal_key(frequency_hz, mode)`** (`db/occupancy_db.py:37`)
   — computes the aggregation key substituting for the durable
   per-emitter identity WiFi/BT devices get for free from a MAC
   address (which RF signals generally lack): round `frequency_hz` to
   the nearest `FREQUENCY_BIN_HZ` (currently a **1000 Hz placeholder**,
   flagged in-code as untuned — reasonable for narrowband HF/VHF/UHF,
   likely wrong at the extremes), combine with `mode` (or the literal
   string `"unknown"` if mode is `None`) into `"<binned_freq>:<mode>"`.
2. **`_connect()`** opens a SQLite connection with
   `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, and
   `busy_timeout=30000` (30s) — this is what lets RX-888's and
   HackRF's producers (and potentially RTL-SDR's, if reactivated) write
   to the same file concurrently without lock contention, since each
   runs as an independent OS process on its own interval.
3. **`INSERT INTO sightings`** — one row per detection event: exact
   `frequency_hz`, `bandwidth_hz` (usually `None` — the producer
   doesn't currently measure occupied bandwidth), paired
   `first/last_seen_sec` + `_ms` timestamps (defaulting to "now" —
   Kismet's `tv_sec`/`tv_usec`-style convention, deliberately not a
   single combined millisecond integer), `source_type`,
   `source_device`, `mode`, `raw_capture_ref` (`None` — no producer
   currently links a sighting to a SigMF capture file), and
   `metadata_json` from Stage 4c.
4. **Upsert into `signals`** keyed on `signal_key`: if the key is new,
   `INSERT` a fresh aggregate row (`first_seen` = `last_seen` = now,
   `total_sightings = 1`); if it already exists, `UPDATE` only
   `last_seen_sec/_ms` and increment `total_sightings`. This is what
   turns a stream of individual `record_sighting()` calls into a
   long-lived per-signal aggregate — the `signals`/`sightings` split
   mirrors kismetdb's `DEVICES`/`PACKETS` pattern (see
   [occupancy-guide.md](occupancy-guide.md) for the full rationale).

Both tables are defined in `db/occupancy_schema.sql`, applied
idempotently (`CREATE TABLE IF NOT EXISTS`) on every `OccupancyDB()`
construction, with a `schema_version` row inserted once on first init.

The whole write path — connect, insert, upsert, commit — happens inside
one `with self._connect()` context per `record_sighting()` call, so
each sighting is its own short-lived write transaction rather than
holding a lock across an entire sweep.

## Stage 6 — process supervision: systemd

Neither producer runs by hand in normal operation — each is installed
as a systemd service so the database fills continuously ("always
watching") rather than only when someone remembers to launch a script.

### RX-888 path

| Unit | Scope | Installed by | Behavior |
|---|---|---|---|
| `radiod@rx888-hf` | system | manual (`/etc/radio/` config deploy) | owns the RX-888 USB device; must be active for the producer to read anything |
| `radiod-occupancy.service` | `--user` | `scripts/phase6-occupancy-producer.sh` | `ExecStart=<venv-python> decode/radiod_occupancy_producer.py --interval 60`; `Restart=on-failure`, `RestartSec=10` |

The install script runs as the normal user (never `sudo`), warns if
`radiod@rx888-hf` isn't active yet (producer will run but read
silence), and enables `loginctl enable-linger` so the `--user` service
survives logout — required because it's a continuous service, not a
periodic timer.

### HackRF path

| Unit | Scope | Installed by | Behavior |
|---|---|---|---|
| `radiod@hackrf-2m` | system | `scripts/phase6-hackrf-occupancy-producer.sh` (root half) | owns the HackRF USB device |
| `radiod-occupancy-hackrf.service` | `--user` | same script (user half, via `TARGET_USER`/`SUDO_USER`) | `ExecStart=<venv-python> decode/radiod_occupancy_producer.py --device hackrf --interval 60` |

This installer does more than the RX-888 one because it manages **two
privilege domains and a hardware-support gate** in one run:

1. Confirms `radiod` is on `PATH` and the config exists.
2. **Gate:** if `radiod@hackrf-2m` isn't already active, does a
   standalone `radiod /etc/radio/radiod@hackrf-2m.conf` load test and
   fails hard, with a specific rebuild hint, if HackRF support isn't
   compiled into the local `radiod` build — this is a real go/no-go
   check, not a formality, per the config file's own header caveat.
3. Enables/starts the system-level `radiod@hackrf-2m` instance, then
   the `--user` producer service *as* `TARGET_USER` (using
   `sudo -u ... XDG_RUNTIME_DIR=... DBUS_SESSION_BUS_ADDRESS=...` to
   reach that user's systemd session from a root-owned script).
4. Enables lingering for `TARGET_USER`, same reasoning as the RX-888
   path.

Both `--user` services depend on their `radiod@*` system instance
without a hard systemd `Requires=` (a `--user` unit can't depend on a
system unit that way) — the dependency is documented in each unit file
instead, and the producer's own "no data → skip" behavior (Stage 4c)
makes an unmet dependency degrade gracefully rather than error.

## End-to-end trace: one real sighting, both devices

**RX-888 / HF example — WWV at 10 MHz:**

```
Antenna → RX-888 MkII (64.8 MSPS, gain 10)
  → radiod@rx888-hf demodulates [wwv-10] as AM, publishes wwv-10000-pcm.local (RTP/5004)
  → radiod_occupancy_producer.py --device rx888 joins that multicast group,
    reads a 2s window, measures ~-20 dBFS (WWV carrier, well above the -30 threshold)
  → record_sighting(frequency_hz=10000000, source_type="radiod",
                     source_device="rx888-hf", mode="am",
                     metadata_json='{"channel":"wwv-10","power_dbfs":-20.1,"threshold_dbfs":-30.0}')
  → signal_key "10000000:am" upserted in `signals`; new row in `sightings`
```

**HackRF / 2m example — the national calling frequency:**

```
Antenna (Comet GP-1) → HackRF One (8 Msps, LNA 40 / mix-gain 24)
  → radiod@hackrf-2m demodulates [2m-calling-146520] as FM, publishes
    2m-calling-146520-pcm.local (RTP/5004)
  → radiod_occupancy_producer.py --device hackrf joins that group, measures
    power against the (still-placeholder) -30 dBFS threshold
  → if active: record_sighting(frequency_hz=146520000, source_type="radiod-hackrf",
                                source_device="hackrf-one", mode="fm", ...)
  → signal_key "146520000:fm" upserted in `signals`
```

## Verifying each stage independently

```bash
# Stage 0/2/6 — who owns each device right now, and is radiod up
./scripts/sdr-mode.sh status
systemctl status radiod@rx888-hf
systemctl status radiod@hackrf-2m

# Stage 3 — is a channel's multicast stream actually live
monitor wwv-10000-pcm.local          # ka9q-radio's own audio monitor tool

# Stage 4 — run the producer by hand, one sweep, verbose
python3 decode/radiod_occupancy_producer.py --device rx888 --once --verbose
python3 decode/radiod_occupancy_producer.py --device hackrf --once --verbose

# Stage 6 — is the continuous service actually running / writing
systemctl --user status radiod-occupancy.service
journalctl --user -u radiod-occupancy.service -f
systemctl --user status radiod-occupancy-hackrf.service

# Stage 5 — did it actually land in the DB
sqlite3 db/occupancy.db "SELECT COUNT(*) FROM sightings WHERE source_type='radiod';"
sqlite3 db/occupancy.db "SELECT COUNT(*) FROM sightings WHERE source_type='radiod-hackrf';"
sqlite3 db/occupancy.db \
  "SELECT frequency_hz, mode, total_sightings, last_seen_sec FROM signals ORDER BY last_seen_sec DESC LIMIT 10;"
```

## Where this hands off

Once a row exists in `signals`/`sightings`, this document's job is
done. From there:

- `openwebui-tools/sigint_occupancy_tool.py`'s `query_occupancy()` /
  `radiod_status()` read `occupancy.db` directly (read-only via
  `PRAGMA query_only=ON`, live against the WAL file) from inside the
  Open WebUI container, and are what the local LLM actually calls.
- `openapi-tools/sigint_openapi_server.py` exposes the same queries
  over HTTP as the currently-active Open WebUI external-tool
  connection path.

Full detail on that leg — container mount setup, why native tools beat
external OpenAPI for local model tool-calling reliability, and the
retired MCP attempt — is in
[db-to-ai-query-path.md](db-to-ai-query-path.md).

## Honest gaps in this specific path

- **HackRF's -30 dBFS threshold is an uncalibrated placeholder** — the
  transport (RTP join, RMS extraction) is verified working against
  live 2m traffic, but ACTIVE/quiet calls on that path shouldn't be
  trusted until a known-quiet-vs-known-active calibration sweep is run
  (see `docs/occupancy-guide.md`'s Calibration section for the method).
- **HackRF driver support in `radiod` is build-dependent and not
  universally confirmed** — Stage 5's install-time gate exists
  specifically because this can silently not work on a given host.
- **The producer parses the repo's copy of each `.conf`, not
  `/etc/radio`'s deployed copy** — the channel list Stage 4 sweeps can
  drift from what `radiod` is actually demodulating if one copy is
  edited without resyncing the other.
- **`bandwidth_hz` and `raw_capture_ref` are always `None` on every
  sighting this path writes** — no producer in this chain currently
  measures occupied bandwidth or links a sighting to a raw SigMF
  capture file, even though the schema has columns for both.
- **RTL-SDR has no active producer at all** in this build — its role
  changed to ad hoc single-frequency tasking (see
  `docs/occupancy-guide.md`), so it's included in `DEVICE_PROFILES` for
  completeness but isn't part of the continuous pipeline described
  above.

## See Also

- `decode/radiod_occupancy_producer.py` — the producer implementation
- `db/occupancy_db.py`, `db/occupancy_schema.sql` — the write path and schema
- `ingest/ka9q-radio/radiod@rx888-hf.conf`, `radiod@hackrf-2m.conf` — the channel configs
- `scripts/sdr-mode.sh`, `scripts/rx888-mode.sh` — device-ownership arbitration
- `scripts/phase6-occupancy-producer.sh`, `scripts/phase6-hackrf-occupancy-producer.sh` — service installers
- `systemd/radiod-occupancy.service`, `systemd/radiod-occupancy-hackrf.service` — unit definitions
- [occupancy-guide.md](occupancy-guide.md) — design rationale, calibration methodology, honest current limitations
- [db-to-ai-query-path.md](db-to-ai-query-path.md) — the downstream DB→AI leg
