-- kismet_bridge/kismet_bridge_schema.sql
--
-- Device-centric local mirror for the Kismet bridge. Deliberately NOT
-- occupancy_schema.sql, even though that schema is itself Kismet-derived
-- (DEVICES/PACKETS -> signals/sightings) — see KISMET-BRIDGE.md's "Why
-- This Isn't a Direct Port" section: occupancy answers "what frequency was
-- active", this answers "what device was present", and reusing one
-- schema for both would conflate two designs that only superficially
-- resemble each other.
--
-- Real adaptation from Kismet's own DEVICES table, and from
-- sovereign-sigint's kismet-to-ai-bridge design: unlike an RF signal (no
-- durable identifier, hence occupancy's frequency+mode binning), a WiFi/BT
-- device has one for free — its MAC address. So there is no PACKETS-style
-- per-detection event table here: Kismet itself is the system of record
-- for packet-level history, this mirror is a periodically-refreshed
-- device-presence cache the gateway's curated REST endpoints feed, not an
-- independent event log. One row per (node_id, mac), upserted on every
-- producer poll.
--
-- node_id (new, vs. sovereign-sigint's single-host design): SIGliere's
-- gateway already serves multiple SIGedge nodes, unlike sovereign-sigint's
-- one Kismet instance on the same box — who observed this device matters.

CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER NOT NULL,
    applied_at_sec  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         TEXT NOT NULL,      -- SIGedge node_id that observed this device
    mac             TEXT NOT NULL,      -- device MAC address, as reported by Kismet
    device_type     TEXT,               -- Kismet's kismet.device.base.type (e.g. "AP", "client", "Wi-Fi Bridged")
    phy             TEXT,               -- Kismet PHY name (e.g. "IEEE802.11", "Bluetooth", "RTL433")
    ssid            TEXT,               -- nullable — only meaningful for dot11 APs
    manufacturer    TEXT,               -- OUI-derived manufacturer, nullable
    signal_dbm      REAL,               -- last observed signal strength, nullable
    first_seen_sec  INTEGER NOT NULL,   -- Kismet's own first_time for this device
    last_seen_sec   INTEGER NOT NULL,   -- Kismet's own last_time for this device
    total_polls     INTEGER NOT NULL DEFAULT 1,  -- how many producer polls have seen this device
    metadata_json   TEXT,               -- raw curated device record, nullable
    UNIQUE(node_id, mac)
);
CREATE INDEX IF NOT EXISTS idx_devices_mac ON devices(mac);
CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen_sec);
CREATE INDEX IF NOT EXISTS idx_devices_node ON devices(node_id);
