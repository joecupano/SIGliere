-- occupancy/occupancy_schema.sql
--
-- Ported from sovereign-sigint's db/occupancy_schema.sql (see
-- ~/sovereign-sigint/docs/occupancy-guide.md for the full design
-- discussion this schema was validated against). Adapted from
-- kismetdb's DEVICES/PACKETS split: `sightings` mirrors PACKETS
-- (per-detection event, lean columns for fast queries), `signals`
-- mirrors DEVICES (a long-lived aggregate identity layer).
--
-- Real adaptation from the reference, unchanged from the original
-- project: WiFi/BT devices have a durable MAC address; most RF signals
-- don't have an equivalent persistent identifier. Substitute: aggregate
-- on (frequency_hz, mode) instead of a hardware address — see
-- occupancy_db.py's FREQUENCY_BIN_HZ for why this needs a binning
-- strategy, not an exact-match key.
--
-- What's different from the original project's schema: SIGliere never
-- touches SIGedge hardware, radiod configuration, or raw IQ (see
-- docs/architecture.md's tier boundary). There is exactly one lawful
-- source of sightings here — the SIGedge gateway's authenticated
-- /status endpoint (KA9Q multicast channel status, forwarded through
-- gateway/), not a local SDR capture. `source_type` is consequently
-- narrower than the original project's ('openwebrx_mqtt' |
-- 'gnuradio_feature_extraction' | 'radiod_capture'); see
-- occupancy_producer.py.
--
-- Timestamp convention: paired epoch-seconds + milliseconds fields,
-- matching kismetdb's actual design (mirrors C's tv_sec/tv_usec
-- struct timeval split) — kept as-is from the original project.

CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER NOT NULL,
    applied_at_sec  INTEGER NOT NULL
);

-- signals: aggregate per (frequency_hz bin, mode) — the DEVICES analog.
CREATE TABLE IF NOT EXISTS signals (
    signal_key      TEXT PRIMARY KEY,   -- see occupancy_db.py: make_signal_key()
    frequency_hz    REAL NOT NULL,      -- representative frequency for this bin
    mode            TEXT,               -- nullable — energy-only detections have no mode
    first_seen_sec  INTEGER NOT NULL,
    first_seen_ms   INTEGER NOT NULL DEFAULT 0,
    last_seen_sec   INTEGER NOT NULL,
    last_seen_ms    INTEGER NOT NULL DEFAULT 0,
    total_sightings INTEGER NOT NULL DEFAULT 0,
    candidate_sigid TEXT,               -- optional link into the SigID mirror (page title)
    detail_json     TEXT                -- aggregate rollup detail, nullable
);
CREATE INDEX IF NOT EXISTS idx_signals_frequency ON signals(frequency_hz);
CREATE INDEX IF NOT EXISTS idx_signals_last_seen ON signals(last_seen_sec);

-- sightings: per-detection event — the PACKETS analog.
CREATE TABLE IF NOT EXISTS sightings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_key      TEXT NOT NULL REFERENCES signals(signal_key),
    frequency_hz    REAL NOT NULL,      -- exact reported frequency, not the bin
    bandwidth_hz    REAL,               -- nullable — not reported by KA9Q channel status
    first_seen_sec  INTEGER NOT NULL,
    first_seen_ms   INTEGER NOT NULL DEFAULT 0,
    last_seen_sec   INTEGER NOT NULL,
    last_seen_ms    INTEGER NOT NULL DEFAULT 0,
    source_type     TEXT NOT NULL,      -- 'sigedge_gateway_status' (only path today)
    source_device   TEXT NOT NULL,      -- logical SIGedge node_id, e.g. 'sigedge-hf'
    mode            TEXT,               -- nullable — radiod preset, e.g. 'usb', 'nfm'
    raw_capture_ref TEXT,               -- unused today; reserved, no capture-ref source exists
    metadata_json   TEXT                -- ssrc/snr_db/sample_rate/multicast_address, nullable
);
CREATE INDEX IF NOT EXISTS idx_sightings_signal_key ON sightings(signal_key);
CREATE INDEX IF NOT EXISTS idx_sightings_frequency ON sightings(frequency_hz);
CREATE INDEX IF NOT EXISTS idx_sightings_first_seen ON sightings(first_seen_sec);
