# SIGedge → SIGliere: Normalized Event Pipeline Spec

Context for implementation in Claude Code. Repo: https://github.com/joecupano/SIGedge
Companion app tier (not yet public): SIGliere, running Ollama + Open WebUI.

Goal: build a correlation-ready SIGINT operations pipeline for property-perimeter
trespasser detection using SDR (cellular presence), Bluetooth, LoRa, and APRS sensors.
This spec extends what already exists in SIGedge (`ai/ollama-bridge`, `channels.yaml`,
`transcripts.jsonl`) rather than replacing it — read those first before implementing.

## 1. Background / current SIGedge state (as of this spec)

- `radiod` (ka9q-radio) owns SDR hardware and republishes IQ/audio as RTP/IP multicast
  streams, addressed per-channel via `status_group`/`data_group` in `channels.yaml`.
- Kismet runs alongside `radiod` for WiFi/Bluetooth/RF protocol monitoring, with its
  own REST/eventbus API and `kismetdb` sqlite storage.
- Decoders (`direwolf` for APRS, `multimon-ng` for POCSAG) consume `pcmrecord` output
  from a channel's multicast audio, following the `rtl_fm | direwolf` pattern.
- `ai/ollama-bridge` is a stub: reads `channels.yaml` for multicast addresses, writes
  speech-to-text to `transcripts.jsonl`, and exposes `get_channel_status()` as a
  read-only tool for Ollama's tool-calling API. `OLLAMA_HOST` env var points at Ollama.
- No LoRa decoder currently exists in SIGedge's decoder set — this is a gap to fill.

## 2. Physical deployment (resolved)

Property is 600 ft diameter. RF collection is a **single site**: one vertical antenna
at 30 ft AGL feeding a passive/active splitter that distributes to all SDRs. This is
decided — do not design for multi-site geolocation in v1.

Implications:

- **No multilateration/TDOA.** One physical antenna location cannot produce bearing
  or position — only presence/absence within range of the mast. `geo.bearing_deg`
  and `geo.target_lat/lon` in the schema below stay `null` for v1; only
  `geo.sensor_lat/lon` (the mast's fixed location) is populated.
- **`sensor_id` collapses to one value** (the mast) across all domains/SDRs, since
  every SDR on the splitter shares the same antenna and coverage area. Don't build
  per-zone or cross-zone trajectory logic — there is only one zone.
- **Correlation is temporal + multi-domain only**, not spatial. See §6.
- **RF budget considerations** to resolve before finalizing hardware:
  - Frequency span across all target signals (~144 MHz APRS through ~5.8 GHz BT)
    is wide for one antenna — needs a genuinely broadband element (discone/log-periodic
    class), or expect uneven sensitivity, likely weakest at the VHF (APRS) end.
  - A passive splitter costs ~3.5–4 dB per port (4-way ≈ 7 dB per leg). Budget an
    LNA immediately after the antenna, before the splitter, rather than compensating
    per-SDR afterward.
  - Coax run loss from the 30 ft mast is frequency-dependent — cheap at 144 MHz,
    costly at 2.4/5.8 GHz. Use low-loss cable (e.g. LMR-400) for BT/WiFi-band legs,
    or locate those SDRs near the mast base and backhaul via Ethernet instead of a
    long coax run.
  - Confirm no terrain/structure shadowing across the 300 ft radius with a walk-test
    on target bands before treating "one antenna covers the whole property" as given.

## 3. Common event schema ("PDW-style" normalized record)

Every sensor/decoder should emit detections in this shape so a correlation engine can
join across sensor types on time + space instead of writing bespoke logic per protocol:

```json
{
  "event_id": "uuid",
  "ts": "2026-09-20T14:32:07.123Z",
  "sensor_id": "west-fence-rtlsdr-01",
  "source": "kismet|direwolf|multimon-ng|lora-gw",
  "domain": "cellular|wifi|bluetooth|aprs|lora|pocsag",
  "protocol": "802.11|BLE|GSM|LoRaWAN|APRS|POCSAG",
  "freq_hz": 915000000,
  "bandwidth_hz": 125000,
  "rssi_dbm": -71,
  "modulation": "LoRa-SF7",
  "identifier": {
    "type": "mac|imsi_partial|callsign|devaddr",
    "value": "AA:BB:CC:DD:EE:FF"
  },
  "geo": {
    "sensor_lat": 0.0,
    "sensor_lon": 0.0,
    "bearing_deg": null,
    "target_lat": null,
    "target_lon": null
  },
  "confidence": 0.8,
  "novelty": "known|unknown|null",
  "tier": "low|medium|high",
  "raw_ref": "transcripts.jsonl#L4821"
}
```

Field notes:
- `identifier.type` varies by domain; leave `value` null if nothing decodable (e.g. raw
  energy detection with no protocol decode).
- `novelty` is set by the correlation engine (known baseline device vs first-seen),
  not by the bridge that emits the raw event. For `identifier.type == "mac"`, resolve
  this by calling SIGliere's existing MAC-library Ollama tool function (§7) —
  do not build a second/parallel allowlist. For `callsign`/`devaddr` identifiers,
  **v1 leaves `novelty` unscored (`null`)** — no known/unknown store for these
  types; APRS/LoRa traffic near the property is lower-volume/lower-priority than
  phone/BT presence, so this was deferred rather than built now. Do not build a
  callsign/devaddr allowlist for v1.
- `raw_ref` points back to the original decoder output line/file for audit trail.
- **MAC randomization caveat**: BLE/WiFi MACs are frequently randomized/rotated by
  modern phones unless the device has associated with a known AP. A "known" MAC
  match against the library is trustworthy; an "unknown" MAC is *not* strong
  evidence of an unrecognized device — it may just be a trusted phone that never
  associated. Treat unmatched BT/WiFi identifiers as a volume/pattern signal, not
  as a per-device identity claim, when feeding the correlation/alert tiers.
- `tier` (resolved decision — supersedes earlier drafts of this section):
  SIGedge/SIGliere's responsibility ends at writing `tier` reliably into the
  `events` row. **An external process (out of scope for this spec) watches the
  SQL database directly for `tier = "high"` rows and handles notification and
  any kinetic response** (e.g. walking the perimeter). Do not build an email
  dispatcher, alerting daemon, or any other notification component in
  SIGedge/SIGliere — the database itself is the integration boundary. `low`/
  `medium` remain queryable the same way via `get_recent_events` for anyone
  who wants to pull them from Open WebUI chat, but that's incidental, not the
  primary consumption path for `high` tier.

## 4. Per-source bridging

| Source | Bridge needed | Mapping notes |
|---|---|---|
| Kismet (WiFi/BT) | New `ai/kismet-bridge` subscribing to Kismet's eventbus/REST (`DEVICE/NEW`, `DEVICE/UPDATE`) | Kismet already decodes; map its device JSON fields directly into the schema above. Easiest source. |
| APRS (direwolf) | Parse direwolf KISS/AGW or text output | APRS position beacons carry callsign + lat/lon already — fill `identifier.type=callsign` and `geo.target_lat/lon` directly from the packet when present. |
| POCSAG (multimon-ng) | Parse multimon-ng text lines | `identifier.value` = capcode. No geo unless triangulated separately. |
| LoRa | **Gap — needs new component.** Either a dedicated LoRa gateway (RAK/Semtech concentrator) or SDR-based decode (`gr-lora`/`gr-lora_sdr`) feeding the same multicast pattern radiod uses for other channels. | Devaddr as identifier once decoded. |
| Cellular presence | Passive GSM/LTE control-channel energy/registration-activity detection only | **Legal boundary**: stay on energy/metadata detection (a phone is present) — do NOT decode IMSI or call content. That crosses into ECPA/wiretap and IMSI-catcher territory. |

## 5. Transport

Add one more multicast group to the existing `channels.yaml` pattern: `events_group`.
Each bridge process (Kismet bridge, APRS parser, POCSAG parser, LoRa gateway bridge)
publishes normalized JSON records (schema in §3) as UDP datagrams to `events_group`.
SIGliere subscribes once to this single group instead of polling every source
individually. Event-rate traffic is small enough that multicast is appropriate (unlike
IQ streams).

## 6. Persistence (SIGliere side)

Upgrade the `transcripts.jsonl` append-only pattern to SQLite once queryability is
needed — Ollama tool-calling requires random-access queries ("what fired in the last
hour on the west fence"), not just tailing a file.

Suggested table:

```sql
CREATE TABLE events (
  event_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  source TEXT NOT NULL,
  domain TEXT NOT NULL,
  protocol TEXT,
  freq_hz INTEGER,
  bandwidth_hz INTEGER,
  rssi_dbm REAL,
  modulation TEXT,
  identifier_type TEXT,
  identifier_value TEXT,
  sensor_lat REAL,
  sensor_lon REAL,
  bearing_deg REAL,
  target_lat REAL,
  target_lon REAL,
  confidence REAL,
  novelty TEXT,
  tier TEXT,
  raw_ref TEXT
);
CREATE INDEX idx_events_ts ON events(ts);
CREATE INDEX idx_events_sensor ON events(sensor_id);
```

## 7. Ollama tool-calling additions

**SIGliere already exposes a MAC-library lookup as an Ollama tool function** —
find its exact name/signature in the SIGliere codebase before writing new code, and
call *that* to resolve `novelty` for `identifier.type == "mac"` events. Do not
reimplement a separate baseline/allowlist store.

Extend the existing `get_channel_status()` stub in `ai/ollama-bridge` with:

- `get_recent_events(domain?, tier?, since?)` — queries the `events` table. No
  `sensor_id` filter needed (single site — see §2). This is a convenience for
  ad hoc chat queries; it is not the primary path for high-tier response, which
  is handled by an external process watching the database directly (§3's `tier`
  note).
- `correlate_events(time_window_s)` — groups events across domains co-occurring
  in time (e.g. a BLE device + GSM registration + APRS packet within 60s = one
  likely "person with phone + HT" composite event rather than three unrelated
  blips), and writes the resulting `tier` back onto the correlated rows. No
  spatial/`geo_radius_m` parameter — single-site deployment (§2) makes this
  purely temporal.

The event ingester (§6) should call the MAC-library tool synchronously per event
with a `mac` identifier and write the resolved `novelty` value directly into the
`events` table, rather than resolving it lazily at query time.

Keep all tools read-only, matching the existing bridge's restriction to
operator-specified channels.

## 8. Implementation task list for Claude Code

1. Read `ai/ollama-bridge` and `channels.yaml` in SIGedge to confirm exact current
   field names/conventions before writing code — match style, don't guess.
2. Add `events_group` to `channels.yaml` schema/docs.
3. Implement `ai/kismet-bridge`: subscribes to Kismet, maps device events to the
   schema in §3, publishes to `events_group`.
4. Implement APRS and POCSAG parsers producing the same schema (extend or wrap
   existing direwolf/multimon-ng invocations rather than replacing them).
5. Stand up SQLite `events` table (§6) on the SIGliere side; write the
   multicast-subscriber → SQLite ingester.
6. Add `get_recent_events` (with `tier` filter) and `correlate_events` tool
   functions to the Ollama bridge, following the existing `get_channel_status()`
   pattern. Wire the ingester to call SIGliere's existing MAC-library tool
   function per §7 for novelty resolution — locate its actual name/signature in
   SIGliere's code first.
7. Flag LoRa decode as an open item — decide gateway vs SDR-decode approach before
   building its bridge.
8. Flag cellular presence detection as needing the passive-energy-only boundary
   documented in §4 — do not implement IMSI/content decode.
9. Antenna/splitter/LNA hardware selection per §2's RF budget notes — resolve
   before or in parallel with software work, since receiver sensitivity affects
   what "detection" thresholds are even meaningful in the schema/confidence field.
10. **Do not build any notification/alerting component** (no email, no SMS, no
    daemon) in SIGedge or SIGliere. Ensure the `events` table (§6) is reliably
    written with `tier` and is reachable by whatever external process the
    property owner points at the database — that process, its trigger logic, and
    its kinetic-response handling are entirely out of scope for this repo.

## 9. Open questions to resolve back in the workflow-discussion thread

None currently. The database is the integration boundary for high-tier response;
everything on the far side of it (notification mechanism, kinetic action such as
perimeter walks) is handled by an external process outside SIGedge/SIGliere and
outside this spec's scope.
