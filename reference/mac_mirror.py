#!/usr/bin/env python3
"""
reference/mac_mirror.py

Sovereign mirror of maclookup.app's free MAC-address vendor (OUI/CID)
database. "MAC lookup should be sovereign" — the Kismet tool
(sigint_kismet_tool.py) sees a stream of device MAC addresses; identifying
the manufacturer behind one should not mean sending that MAC out to a
third-party API at query time. This script pulls the whole database down
once (and re-checks periodically, via systemd/mac-mirror.timer) so
openwebui-tools/mac_lookup_tool.py can answer entirely from local disk.

THE DOWNLOAD IS A SIGNED LINK, NOT A STATIC URL — confirmed 2026-08-11
against the live site: https://maclookup.app/downloads/json-database
server-renders a fresh `<a href="/downloads/json-database/get-db?t=<date>&
h=<hash>">` on every page load. `t`/`h` change per request, so the actual
data URL can't be hardcoded — this script re-fetches the landing page each
run, scrapes that link out, then follows it. That's two requests per run,
not one; both are made through the same session/User-Agent.

Output layout:
  /data/reference/mac-vendors/mac-vendors.json    — the JSON array, as-is
                                                     from maclookup.app
  /data/reference/mac-vendors/mac-vendors.meta.json — {source_url,
                                                     synced_at, entry_count,
                                                     content_hash}, for
                                                     humans/scripts that
                                                     don't want to open
                                                     manifest.db
  /data/reference/mac-vendors/manifest.db          — sync state (see
                                                     mac_manifest.py)

Schema of each entry in mac-vendors.json (confirmed against a live
download, not guessed):
  {"macPrefix": "00:00:0C", "vendorName": "Cisco Systems, Inc",
   "private": false, "blockType": "MA-L", "lastUpdate": "2015/11/17"}
`macPrefix` is hex pairs colon-joined but NOT always a 24-bit/6-hex-digit
OUI — IAB and MA-M/MA-S/CID block types carry longer prefixes (28-bit/7
hex digits, 36-bit/9 hex digits) for sub-delegated ranges. The lookup tool
does longest-prefix-match across all three lengths for this reason.
`private: true` entries have empty vendorName/blockType — the registrant
opted out of public disclosure; that's a real, expected row, not corrupt
data.

Usage:
  python3 mac_mirror.py                 # normal run — fetch, skip write if unchanged
  python3 mac_mirror.py --once          # same; explicit for systemd
  python3 mac_mirror.py --dry-run       # report only, no writes
  python3 mac_mirror.py --force         # write even if content hash is unchanged
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from mac_manifest import MacManifest

BASE_URL = "https://maclookup.app"
LANDING_PATH = "/downloads/json-database"

USER_AGENT = (
    "Sigliere-mirror/1.0 "
    "(https://github.com/joecupano/Sigliere; personal MAC vendor reference mirror)"
)
REQUEST_TIMEOUT = 60

DEFAULT_OUTPUT_ROOT = Path("/data/reference/mac-vendors")

# Sanity bounds on the downloaded payload — catches a broken scrape (e.g.
# the landing page's link markup changed) or a truncated download before
# it silently overwrites a good local copy with garbage. Not exact —
# maclookup.app's real database is ~58k entries as of 2026-08; these are
# generous margins around that, not a tight schema check.
MIN_EXPECTED_ENTRIES = 10_000
REQUIRED_KEYS = {"macPrefix", "vendorName"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mac_mirror")


class MacMirrorError(Exception):
    pass


def discover_download_url(session: requests.Session) -> str:
    """Scrape the signed get-db link off the landing page. See module
    docstring — this link is regenerated per page load, so it can't be
    hardcoded or cached across runs."""
    url = urljoin(BASE_URL, LANDING_PATH)
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    m = re.search(r'href="(/downloads/json-database/get-db\?[^"]+)"', resp.text)
    if not m:
        raise MacMirrorError(
            f"Could not find the get-db download link on {url}. The page's "
            "markup may have changed — inspect a fresh fetch of that URL "
            "and update the regex in discover_download_url()."
        )
    href = m.group(1).replace("&amp;", "&")
    return urljoin(BASE_URL, href)


def download_database(session: requests.Session, download_url: str) -> bytes:
    resp = session.get(download_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def validate_payload(raw: bytes) -> list:
    """Parse + sanity-check before anything touches disk. Raises
    MacMirrorError on anything that looks like a broken/partial fetch
    rather than a real database."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MacMirrorError(f"Downloaded payload is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise MacMirrorError(f"Expected a JSON array at the top level, got {type(data).__name__}")

    if len(data) < MIN_EXPECTED_ENTRIES:
        raise MacMirrorError(
            f"Downloaded database has only {len(data)} entries — expected at "
            f"least {MIN_EXPECTED_ENTRIES}. Refusing to treat this as a good "
            "mirror; likely a truncated download or a changed page format."
        )

    sample = data[0]
    if not isinstance(sample, dict) or not REQUIRED_KEYS.issubset(sample.keys()):
        raise MacMirrorError(
            f"First entry is missing expected keys {REQUIRED_KEYS} — got "
            f"{sample!r}. The upstream schema may have changed."
        )

    return data


def run(output_root: Path, dry_run: bool, force: bool) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = MacManifest(output_root / "manifest.db")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    run_id = manifest.start_run()
    try:
        download_url = discover_download_url(session)
        log.info("Resolved download URL: %s", download_url)

        raw = download_database(session, download_url)
        content_hash = hashlib.sha256(raw).hexdigest()

        entries = validate_payload(raw)
        log.info("Downloaded %d entries (%d bytes, sha256=%s)", len(entries), len(raw), content_hash[:12])

        last_hash = manifest.last_content_hash()
        unchanged = (last_hash == content_hash) and not force

        if dry_run:
            outcome = "unchanged" if unchanged else "would-update"
            log.info("[dry-run] %s (last_hash=%s)", outcome, (last_hash or "none")[:12])
            manifest.finish_run(run_id, outcome, len(entries), "success")
            return {"outcome": outcome, "entry_count": len(entries)}

        if unchanged:
            log.info("Content unchanged since last sync — skipping write.")
            manifest.finish_run(run_id, "unchanged", len(entries), "success")
            return {"outcome": "unchanged", "entry_count": len(entries)}

        data_path = output_root / "mac-vendors.json"
        meta_path = output_root / "mac-vendors.meta.json"
        synced_at = datetime.now(timezone.utc).isoformat()

        # Write-then-rename so the tool (which may be reading concurrently
        # inside the container) never sees a partially-written file.
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output_root, prefix=".mac-vendors-", suffix=".tmp", delete=False
        ) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        # tempfile creates with mode 0600 regardless of umask, and rename
        # preserves that — fix it up explicitly before it lands at its real
        # name, or this mirror is unreadable by anything but the syncing
        # user, including Open WebUI's container reading it read-only under
        # a different, UID-mapped identity.
        tmp_path.chmod(0o644)
        tmp_path.replace(data_path)

        meta_path.write_text(
            json.dumps(
                {
                    "source_url": download_url,
                    "synced_at": synced_at,
                    "entry_count": len(entries),
                    "content_hash": content_hash,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # Explicit, not umask-dependent — same reasoning as tmp_path above.
        meta_path.chmod(0o644)

        manifest.record_file_synced(content_hash, len(entries), download_url)
        manifest.finish_run(run_id, "updated", len(entries), "success")
        log.info("Wrote %s (%d entries)", data_path, len(entries))
        return {"outcome": "updated", "entry_count": len(entries)}

    except BaseException as exc:
        manifest.finish_run(run_id, "error", None, "error", str(exc))
        raise


def main():
    parser = argparse.ArgumentParser(description="Sigliere MAC vendor database mirror")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="no-op flag for clarity in systemd unit")
    parser.add_argument("--force", action="store_true", help="write even if content hash is unchanged")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    log.info("Starting MAC vendor mirror sync (dry_run=%s, force=%s)", args.dry_run, args.force)
    try:
        result = run(args.output_root, args.dry_run, args.force)
    except (MacMirrorError, requests.RequestException) as exc:
        log.error("%s", exc)
        return 1

    log.info("Done. outcome=%s entry_count=%s", result["outcome"], result["entry_count"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
