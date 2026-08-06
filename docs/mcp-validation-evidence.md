# MCP Validation Evidence

This log captures objective post-merge validation evidence for the MCP server path.

## 2026-08-05 Dry-Run Validation (Test Server)

- Timestamp (UTC): 2026-08-05T04:39:30Z
- Branch: main
- Commit: 4fc8715
- Validation script: scripts/phase6-mcp-server-validate.sh
- Container image: localhost/sigliere-mcp:latest
- Runtime mode: SIGLIERE_MCP_DRY_RUN=true

### Command

```bash
cd /home/baldrick/sigliere
bash scripts/phase6-mcp-server-validate.sh
```

### Results

- health endpoint: PASS
- node inventory: PASS (3 nodes: rx888-hf, hackrf-vhf-uhf, rtlsdr-v4)
- frequency routing: PASS (146.520 MHz routed to hackrf-vhf-uhf)
- operator action path: PASS (`set_frequency` returned dry-run success)
- overall validation: PASS

### Captured Output (summary)

```text
[mcp-validate] health: {"ok":true,"role":"analyst","node_count":3,"dry_run":true}
[mcp-validate] route: {"role":"analyst","frequency_hz":146520000.0,"node_id":"hackrf-vhf-uhf","radiod_instance":"hackrf-vhf-uhf"}
[mcp-validate] set_frequency: {"dry_run":true,"node_id":"hackrf-vhf-uhf","frequency_hz":146520000.0,"mode":"nfm","note":"Dry-run enabled; no radiod change was sent.","role":"operator"}
[mcp-validate] PASS
```

## 2026-08-05 Managed Service + Open WebUI Container-Path Validation

- Timestamp (UTC): 2026-08-05T05:16:08Z
- Branch: main
- Commit under test: c4c7296
- Managed service: `sigliere-mcp.service`

### Service Activation Result

- Installed Quadlet to `~/.config/containers/systemd/sigliere-mcp.container`.
- Initial state observed as `inactive (dead)`.
- Started service manually and verified `active` state.
- Running container verified: `sigliere-mcp`.

### Open WebUI Network-Path Role Tests

- Test origin: inside `open-webui` container.
- Endpoint `http://0.0.0.0:8140`:
	- `healthz`: FAIL (`connection refused`)
	- `set_frequency` analyst/operator: FAIL (`connection refused`)
- Endpoint `http://host.containers.internal:8140`:
	- `healthz` with analyst token: PASS (HTTP 200)
	- `set_frequency` with analyst token: PASS expected deny (HTTP 403)
	- `set_frequency` with operator token: PASS (HTTP 200, dry-run response)

### Remediation Applied

- Updated `scripts/openwebui-mcp-command.sh` to emit `host.containers.internal`
	when `SIGLIERE_MCP_HOST=0.0.0.0`.

### Generated Settings After Fix

```text
Name: Sigliere MCP
Type: Streamable HTTP
URL: http://host.containers.internal:8140
Headers:
	Authorization: Bearer operator-token
```

## 2026-08-05 Controlled Non-Dry-Run Action Test

- Timestamp (UTC): 2026-08-05T05:05:04Z
- Branch: main
- Commit: 29d2d18
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `hackrf-vhf-uhf` at 146.520 MHz

### Command Pattern

- Started ephemeral MCP container with dry-run disabled and test role tokens.
- Called `/healthz`, `/route_frequency`, `/radiod_status/hackrf-vhf-uhf`, and `/set_frequency`.

### Results

- health endpoint: PASS
- route_frequency: PASS
- radiod_status: DEGRADED (`active: error:FileNotFoundError`, socket unreachable)
- set_frequency: FAIL (HTTP 500)

### Failure Detail

```text
HTTP=500
{"detail":"radiod command failed: module 'ka9q' has no attribute 'Client'"}
```

### Interpretation

- The live action path is blocked by adapter/library API mismatch in `mcp-server/src/radiod_adapter.py`.
- Current adapter assumes `ka9q.Client`, but installed `ka9q-python` version does not expose that symbol.

### Required Remediation Before Production Action Mode

1. Update `mcp-server/src/radiod_adapter.py` to match the actual `ka9q-python` API used on this host.
2. Re-run this controlled non-dry-run test and require HTTP 200 on `set_frequency`.
3. Keep dry-run mode as default until live action path passes.

## 2026-08-05 Controlled Non-Dry-Run Action Retest (Remediated)

- Timestamp (UTC): 2026-08-05T05:09:06Z
- Branch: main
- Commit under test: e61b86d
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `hackrf-vhf-uhf` at 146.520 MHz

### Remediation Applied

1. Replaced legacy `ka9q.Client` usage with `ka9q.RadiodControl` flow in `mcp-server/src/radiod_adapter.py`.
2. Added explicit `status_address` values to `mcp-server/config/nodes.json` so the container does not depend on `avahi-browse` discovery for this host.
3. Plumbed optional `status_address` through server config in `mcp-server/src/sigliere_mcp_server.py`.

### Results

- health endpoint: PASS
- set_frequency: PASS (HTTP 200)
- response: includes `status: "applied"` and resolved `status_address`

### Captured Output (summary)

```text
HTTP=200
{"dry_run":false,"node_id":"hackrf-vhf-uhf","frequency_hz":146520000.0,"mode":"nfm","preset":"nfm","status_address":"239.172.80.224","status":"applied","role":"operator"}
```

### Residual Notes

- Container logs reported `TTL=0` warnings for multicast stream distribution; this did not block control-path success.

## 2026-08-05 Controlled Non-Dry-Run RX-888 Action Test

- Timestamp (UTC): 2026-08-05T05:10:42Z
- Branch: main
- Commit under test: cfb5d84
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `rx888-hf` at 7.100 MHz (`usb`)

### Command Pattern

- Started ephemeral MCP container with dry-run disabled and test role tokens.
- Called `/route_frequency` for `7100000` and then `/set_frequency` for `rx888-hf`.

### Results

- route_frequency: PASS (`7100000` mapped to `rx888-hf`)
- set_frequency: PASS (HTTP 200)

### Captured Output (summary)

```text
HTTP=200
{"dry_run":false,"node_id":"rx888-hf","frequency_hz":7100000.0,"mode":"usb","preset":"usb","status_address":"239.95.191.236","status":"applied","role":"operator"}
```

### Residual Notes

- Container logs reported `TTL=0` warnings for multicast stream distribution; this did not block control-path success.

## Evidence Policy

- Add a new dated entry for each significant MCP change merged to main.
- Record branch, commit, runtime mode, and command used.
- Prefer dry-run evidence first; add a separate section for controlled live tests.

## 2026-08-05 Open WebUI Integration Readiness Check

- Timestamp (UTC): 2026-08-05T04:41:27Z
- Branch: main
- Commit: cafd650
- Command: `bash scripts/openwebui-mcp-command.sh`

### Result

- status: BLOCKED (configuration prerequisite missing)
- blocker: `/home/baldrick/.config/sigliere/mcp.env` not found

### Remediation

1. Create the host env file from `mcp-server/mcp.env.example`.
2. Fill in real token values for `SIGLIERE_MCP_TOKENS_JSON` and `SIGLIERE_OPERATOR_TOKEN`.
3. Re-run `bash scripts/openwebui-mcp-command.sh` and capture generated URL/header output.
4. Paste output into Open WebUI MCP Tool settings and validate tool loading.

## 2026-08-05 Open WebUI Settings Generation (Unblocked)

- Timestamp (UTC): 2026-08-05T04:41:54Z
- Branch: main
- Commit: fb70162
- Local setup: created `/home/baldrick/.config/sigliere/mcp.env` from `mcp-server/mcp.env.example`
- Command: `bash scripts/openwebui-mcp-command.sh`

### Result

- status: PASS (settings generated)
- output:

```text
Name: Sigliere MCP
Type: Streamable HTTP
URL: http://0.0.0.0:8140
Headers:
	Authorization: Bearer operator-token
```

### Follow-up Required

- Replace placeholder token values in `/home/baldrick/.config/sigliere/mcp.env` before production use.

## 2026-08-05 Dry-Run Validation After Secret-Key Durability Change

- Timestamp (UTC): 2026-08-05T05:04:03Z
- Branch: main
- Commit: 02a0728
- Validation script: scripts/phase6-mcp-server-validate.sh
- Container image: localhost/sigliere-mcp:latest
- Runtime mode: SIGLIERE_MCP_DRY_RUN=true

### Command

```bash
cd /home/baldrick/sigliere
bash scripts/phase6-mcp-server-validate.sh
```

### Results

- health endpoint: PASS
- node inventory: PASS (3 nodes: rx888-hf, hackrf-vhf-uhf, rtlsdr-v4)
- frequency routing: PASS (146.520 MHz routed to hackrf-vhf-uhf)
- operator action path: PASS (`set_frequency` returned dry-run success)
- overall validation: PASS

### Captured Output (summary)

```text
[mcp-validate] health: {"ok":true,"role":"analyst","node_count":3,"dry_run":true}
[mcp-validate] route: {"role":"analyst","frequency_hz":146520000.0,"node_id":"hackrf-vhf-uhf","radiod_instance":"hackrf-vhf-uhf"}
[mcp-validate] set_frequency: {"dry_run":true,"node_id":"hackrf-vhf-uhf","frequency_hz":146520000.0,"mode":"nfm","note":"Dry-run enabled; no radiod change was sent.","role":"operator"}
[mcp-validate] PASS
```

## 2026-08-05 rtlsdr-v4 Live-Test Gap Investigation (Blocked)

- Timestamp (UTC): 2026-08-05T06:34:00Z
- Branch: main
- Scope: attempt to extend the controlled non-dry-run `set_frequency` test
  (already PASS for `hackrf-vhf-uhf` and `rx888-hf`) to the third node,
  `rtlsdr-v4`.

### Root Cause Found

`node_id`/`radiod_instance` `rtlsdr-v4` in `mcp-server/config/nodes.json`
did not correspond to any deployed radiod config on this host:

- `radiod@rtlsdr-v4.service` was `loaded` (systemd instantiated it from
  the generic `radiod@.service` template) but `inactive (dead)` —
  never started.
- That template requires `/etc/radio/radiod@rtlsdr-v4.conf`. Only
  `radiod@rx888-hf.conf` and `radiod@hackrf-2m.conf` were deployed to
  `/etc/radio/`; no `rtlsdr-v4` conf existed anywhere.
- The repo's only RTL-SDR config is
  `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf`, instance name
  `rtlsdr-adhoc` — never deployed, and named differently from the
  `nodes.json` entry.

### Two Stale/Unconfirmed Claims in `radiod@rtlsdr-adhoc.conf`, Checked Against the Installed Build

The conf file's own header flagged two prerequisites as unconfirmed.
Checked both against `/opt/sovereign-sigint/src/ka9q-radio` (the source
this host's `radiod`/`control` were built from):

1. **"RTL-SDR under radiod needs the companion rtlsdrd daemon running
   first" — found to be incorrect for this build.** `radiod` loads RTL-SDR
   support directly via `src/rtlsdr.c` / `rtlsdr.so`, the same
   plugin-driver pattern already working for `rx888-hf` and `hackrf-2m`
   (no companion daemon for either). No `rtlsdrd` binary exists on this
   host (`find / -iname '*rtlsdr*'` found none), and
   `docs/SDR/rtlsdr.md` in the ka9q-radio source describes direct
   `[global] hardware = rtlsdr` config with no separate daemon. This
   blocker does not apply.
2. **"Validate this file with: `radiod -I` ..." — the `-I` flag does not
   exist in this build.** `radiod`'s usage banner lists `[-I]`, but the
   actual `getopt(argc, argv, "N:vV")` call in
   `src/main.c` only recognizes `-N`, `-v`, `-V`. Confirmed live:
   `radiod --help` errors on unknown option before reaching a `-I`
   branch. There is no config-validate/dry-run flag on this build —
   only starting the service actually exercises the conf.

### Action Taken

- Deployed `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf` unchanged to
  `/etc/radio/radiod@rtlsdr-v4.conf` (writable without root — `/etc/radio`
  is `radio`-group-writable and this session's user is in that group).
  `mcp-server/config/nodes.json` was intentionally left unchanged
  (`node_id`/`radiod_instance` stay `rtlsdr-v4`), per the deployment
  path chosen for this fix.

### Blocked On

Starting/enabling the service requires root; this session has no
passwordless `sudo`:

```text
$ systemctl start radiod@rtlsdr-v4
Failed to start radiod@rtlsdr-v4.service: Interactive authentication required.
$ systemctl enable radiod@rtlsdr-v4
Failed to enable unit: Interactive authentication required.
```

### Required Remediation (operator action, needs root)

```bash
sudo systemctl enable --now radiod@rtlsdr-v4
systemctl status radiod@rtlsdr-v4   # expect: active (running)
journalctl -u radiod@rtlsdr-v4 -n 40 --no-pager   # confirm no rtlsdr USB claim errors
```

Then re-run the same controlled non-dry-run pattern used for the other
two nodes (see the RX-888 and hackrf-vhf-uhf sections above), targeting
`rtlsdr-v4`. Suggested first frequency: pick a value with **no**
existing fixed channel to genuinely exercise the freq=0 dynamic-channel
path this conf relies on (unlike the hackrf test, which retasked a
pre-existing `[2m-calling-146520]` channel — see Residual Notes below).

### Residual Note — Untested Assumption Carried Forward

The prior `hackrf-vhf-uhf` and `rx888-hf` live tests both succeeded, but
neither is a clean precedent for `rtlsdr-v4`'s config shape:
`146.520 MHz` matched an existing fixed `[2m-calling-146520]` channel in
`radiod@hackrf-2m.conf`, and while `7.100 MHz usb` on `rx888-hf` did
require the adapter to create a new channel, `rx888-hf` still has other
fixed channels already running. `radiod@rtlsdr-adhoc.conf` has **zero**
fixed channels — only a single `freq = 0` prototype — so this will be
the first real test of `ka9q.RadiodControl.create_channel`/
`ensure_channel` against an instance with no pre-existing channels at
all. Treat a PASS here as new evidence, not a foregone conclusion.

### `nodes.json` Gap Not Addressed by This Fix

`rtlsdr-v4`'s entry in `mcp-server/config/nodes.json` still has no
`status_address`, unlike the other two nodes (which got one explicitly
during earlier remediation specifically to avoid depending on avahi
discovery). If discovery is flaky when the live test is run, that is
the next thing to fix — add an explicit `status_address` for
`rtlsdr-v4` matching whatever `status = rtlsdr-adhoc-status.local`
resolves to on this LAN.

## 2026-08-05 rtlsdr-v4 Service Start + Live Test (Service PASS, Control Action FAIL)

- Timestamp (UTC): 2026-08-05T06:40:00Z–06:52:00Z
- Branch: main
- Scope: continuation of the above investigation, after the operator ran
  `sudo systemctl enable --now radiod@rtlsdr-v4` on this host.

### Service Start Result: PASS, With Explained Warnings

`journalctl -u radiod@rtlsdr-v4` showed the service reach
`active (running)` with hardware attached:

```text
Dynamically loading rtlsdr hardware driver from /usr/local/lib/ka9q-radio/rtlsdr.so
[rtlsdr] key "iface" not found
[rtlsdr] key "status" not found
[rtlsdr] key "data" not found
[rtlsdr] key "ssrc" not found
[rtlsdr] key "gainmode" not found
Found 1 RTL-SDR device: #0 (Generic RTL2832U OEM): Realtek RTL2838UHIDIR 00000001
Using RTL-SDR #0, serial 00000001
Found Rafael Micro R820T tuner
[R82XX] PLL not locked!  (x3, during init before first lock)
Exact sample rate is: 1000000.026491 Hz
sovereign-sigint RTL-SDR ad hoc single-frequency tasking, samprate 1,000,000 Hz, agc 0, gain 0, ...
rtlsdr thread running
[ad-hoc] 1 channels started
1 total demodulators started
```

**The five `[rtlsdr] key "..." not found` warnings are explained, not a
regression:** those five keys (`iface`, `status`, `data`, `ssrc`,
`gainmode`) were set inside the `[rtlsdr]` hardware section, which this
build's `rtlsdr.so` front-end driver does not parse those keys from
(confirmed by contrast: `radiod@rx888-hf.conf` sets the identical key
names in its `[rx888]` hardware section and that driver *does* accept
them, with no warnings). What actually matters — `[global] status`
(the control channel) and `[AD-HOC] data` (the demodulated-audio
channel) — are in different sections, were not flagged, and were
confirmed live via `avahi-publish-address`:

```text
rtlsdr-adhoc-status.local  -> 239.234.164.106  (port 5006, _ka9q-ctl._udp, TTL=1)
rtlsdr-adhoc-pcm.local     -> 239.152.12.134   (port 5004, _rtp._udp, TTL=0)
rtlsdr-v4-pcm.local        -> 239.86.23.217    (auto-named; front-end raw-IQ stream naming was dropped along with the [rtlsdr]-section keys, cosmetic only)
```

Added `"status_address": "239.234.164.106"` to `rtlsdr-v4` in
`mcp-server/config/nodes.json`, matching the remediation already applied
to the other two nodes.

### Live `set_frequency` Result: FAIL (new failure mode, not the earlier `ka9q.Client` bug)

Ran the same ephemeral-container, non-dry-run pattern used for the
other two nodes (`SIGLIERE_MCP_DRY_RUN=false`, test operator token),
targeting `rtlsdr-v4` at 146.520 MHz `nfm`:

```text
POST /set_frequency {"node_id":"rtlsdr-v4","frequency_hz":146520000,"mode":"nfm"}
HTTP=500
{"detail":"radiod command failed: No status response received for SSRC 1345155156 within 5.0s"}
```

Reproduced twice, identically (same SSRC both times — `allocate_ssrc()`
is a deterministic hash of the request parameters, not random, so this
is a stable repro, not a flake). Container logs show radiod *is*
sending something back — repeated `Radiod reporting TTL=0 for SSRC
1677018585: Multicast data restricted to localhost loopback only!` (14–17
times per attempt) — but never the specific status reply the client's
wait loop is matching on for either SSRC it tries
(`ensure_channel`'s auto-allocated SSRC `1345155156`, then the
`create_channel` fallback's SSRC `1677018585`). `radiod`'s own journal
(`journalctl -u radiod@rtlsdr-v4`) recorded **zero** new lines during
either attempt — inconclusive on its own since the unit isn't run with
`-v`, but consistent with the command not being acted on the way it is
for the other two nodes.

### Interpretation

This lines up with the exact gap `radiod@rtlsdr-adhoc.conf`'s own
header flagged as unconfirmed from the start: tasking a `freq = 0`
"prototype" channel (this instance's *only* channel — no fixed channel
list, unlike `rx888-hf`/`hackrf-2m` which both have other channels
already running) via `ka9q-python`'s generic
`ensure_channel`/`create_channel` has not been shown to work the same
way it does against an instance with pre-existing channels. This is new
information, not a repeat of the earlier `ka9q.Client` API-mismatch bug
(that one is fixed and stays fixed).

### Attempted Diagnostic, Blocked

Tried a packet capture on the control port (`tcpdump -i any udp port
5006`) during a retry to see whether radiod is replying at the wire
level at all. Blocked: `tcpdump: You don't have permission to perform
this capture on that device` — this session has no raw-capture
capability, same root gap as the systemd start earlier.

### Required Remediation (operator action, needs root)

1. `sudo tcpdump -i any -n udp port 5006 -c 40` while re-running the
   `set_frequency` call above, to confirm whether radiod is replying to
   the specific command packet at all, or only sending unrelated
   periodic status broadcasts.
2. Consider restarting `radiod@rtlsdr-v4` with `-v` (`ExecStart=... -N
   %i -v /etc/radio/radiod@%i.conf`, temporary override) to get
   per-command logging in `journalctl` during a retry.
3. Do not add `[freq-name]` fixed-channel sections to
   `radiod@rtlsdr-adhoc.conf` as a workaround without deciding that
   trade-off deliberately — the whole point of this conf is staying
   frequency-agnostic per its own header; converting it to a
   fixed-channel config changes what this node is for.

### Current Status

- `radiod@rtlsdr-v4.service`: **running**, hardware attached, control
  channel and demod-audio channel confirmed live over mDNS/multicast.
- `mcp-server/config/nodes.json`: updated with `rtlsdr-v4`'s real
  `status_address`.
- Live `set_frequency` control action against `rtlsdr-v4`: **still
  blocked** — new, more specific failure than before, root-level
  packet capture needed to go further.

## 2026-08-05 rtlsdr-v4 Root Cause Isolated: Network Ruled Out, Confirmation-Reply Gap Found

- Timestamp (UTC): 2026-08-05T06:53:00Z–07:16:19Z
- Branch: main
- Scope: continuation of the investigation above, with operator-run root
  diagnostics (packet capture, IGMP membership check, verbose radiod
  restart) between each retry. `set_frequency` against `rtlsdr-v4` was
  fired **eight times** total across this session (`07:03:31`, `07:03:32`
  wave, `07:06:28`, `07:11:56`, `07:16:19`, plus earlier attempts logged
  above) — every single one failed identically:
  `No status response received for SSRC 1345155156 within 5.0s`
  (same SSRC every time — `allocate_ssrc()` is a deterministic hash of
  request parameters, confirming a stable repro, not a flake).

### Network Layer: Ruled Out

Three checks, in order, each closing off a plausible network-level
explanation:

1. **`tcpdump -i any host 239.234.164.106`** (the correct multicast
   group and interface, after an earlier `-i lo`-only attempt wrongly
   came back empty) showed our client's command packets (`56833 →
   239.234.164.106:5006`) genuinely leaving the host on `eno1`,
   alongside `rtlsdr-v4`'s own periodic heartbeat (`5006 → 5006`,
   confirming the instance is alive and broadcasting). **Zero inbound
   reply packets** in a full clean 20-second capture spanning two
   command attempts.
2. **IGMP membership** (`ip maddr show`) confirmed `239.234.164.106` is
   properly joined — 2 users on `eno1`, also joined on `lo`. Group
   membership and routing are intact; this isn't a join/routing
   failure.
3. Ruled out RTL-SDR hardware/PLL-retune as the cause too (the
   competing hypothesis after finding `[R82XX] PLL not locked!` warnings
   at startup) — see below, the verbose log shows radiod never even
   attempts a retune.

### Decisive Evidence: Verbose (`-v -v`) radiod Log During a Live Attempt

Temporarily overrode `ExecStart` via a `--runtime` (non-persistent,
`/run/`-only, gone on next reboot) systemd drop-in to add `-v -v`, then
fired `set_frequency` again while tailing `journalctl -u
radiod@rtlsdr-v4 -f` live:

```text
07:16:19 start_demod: ssrc 1,345,155,156, output rtlsdr-v4-pcm.local, demod 1, freq 0.000, preset fm, filter (-8,000,+8,000)
07:16:19 dynamically started ssrc 1,345,155,156
```

**radiod received the command and created the channel — the same SSRC
our client generated.** This rules out both the network layer (packet
plainly arrived and was acted on) and the freq=0/prototype-tasking
concern flagged in the conf's own header (dynamic channel creation
against this instance works — it created one, on request, from
nothing). But it started at **`freq 0.000`**, never retuned to the
requested 146.520 MHz, and no further log line ever appears for this
SSRC afterward.

### Root Cause

`mcp-server/src/radiod_adapter.py`'s `set_frequency()` flow is two
separate steps: `_ensure_ssrc()` (calls `ensure_channel()`, then falls
back to `create_channel()`) to establish the channel, **then**
`control.tune(ssrc=ssrc, frequency_hz=..., ...)` to actually set the
real frequency. `create_channel()` succeeded on radiod's side (per the
log above) but its own creation-confirmation status reply never reached
the client within the library's 5-second wait — and
`_ensure_ssrc()`'s `create_channel()` branch has no `try/except` around
it (unlike the `ensure_channel()` branch just above it, which does).
The resulting `TimeoutError` propagates straight up through
`_ensure_ssrc()` to `set_frequency()`'s outer handler, which wraps and
re-raises it. **`control.tune()` is never called at all** — the
channel is left parked at 0 Hz and self-expires per the conf's own
`Template.lifetime` (~20s after last command, confirmed in
`ka9q-radio`'s `radio.c`), leaving no persistent residue, but also
never accomplishing the requested tune.

This is a confirmation-reply delivery gap specific to newly, dynamically
created channels on this instance — not the freq=0/prototype semantics
originally suspected (ruled out — dynamic creation works), not a
network/multicast problem (ruled out — packets arrive, group membership
is correct), and not the RTL-SDR PLL/retune concern (ruled out — radiod
never even reaches a retune step). Whether radiod's status-broadcast
cadence for `rtlsdr-v4` is simply slower than the 5s client timeout
(this instance runs one dormant channel vs. `rx888-hf`'s constant
churn across 15+ channels, which may drive more frequent status
broadcasts and mask the same underlying latency there) is the next
thing to check — but that is a hypothesis, not confirmed; do not act on
it without verifying against `ka9q-python`'s actual status-broadcast
trigger logic first.

### Required Remediation

1. In `mcp-server/src/radiod_adapter.py`, wrap the `create_channel()`
   fallback branch in `_ensure_ssrc()` with the same `try/except`
   pattern already used for `ensure_channel()` above it, OR raise the
   client-side confirmation timeout for this code path specifically —
   pick one deliberately; don't silently swallow both branches' errors,
   per this repo's fail-loud guardrail.
2. Confirm whether raising the timeout (e.g. to 10–15s) alone resolves
   this before changing error-handling behavior — cheaper fix if it
   works, and tells us whether this is purely a latency mismatch or a
   reply that never comes at all.
3. Re-run this exact live test after either fix and require the full
   round trip (`create_channel` + `tune`) to complete with the channel
   actually landing on 146.520 MHz, not just channel creation.

### Housekeeping

- The `-v -v` verbose override lives at
  `/run/systemd/system/radiod@rtlsdr-v4.service.d/override.conf`.
  Because it was applied via the `--runtime` (`/run/`) path rather than
  `/etc/`, it does **not** survive a reboot and needs no manual
  cleanup — noting this so a future session doesn't go looking for
  where verbose logging was "supposed" to have been reverted.
- The ephemeral `sigliere-mcp-livetest` test container used for all
  eight attempts in this session has been removed. The persistent
  `sigliere-mcp` managed service (dry-run mode) was left untouched
  throughout.

## 2026-08-06 rtlsdr-v4 Retest After Fail-Loud Fix (Diagnostics Improved, Live Action Still FAIL)

- Timestamp (host local, from journalctl; UTC offset not confirmed for
  this session): 2026-08-06T01:25:44
- Branch: main
- Commit under test: `64168c4` ("Fail loud with specific errors in MCP
  set_frequency channel allocation")
- Runtime mode: `SIGLIERE_MCP_DRY_RUN=false`
- Scope: retest of the live `set_frequency` call against `rtlsdr-v4`
  (146.520 MHz, `nfm`) that failed identically eight times in the prior
  session, now against the fixed `mcp-server/src/radiod_adapter.py`.

### Command Pattern

- Rebuilt `localhost/sigliere-mcp:latest` from `64168c4` (image must be
  rebuilt for a source change to take effect — `Containerfile` `COPY`s
  `mcp-server/src` at build time, it isn't a live-mounted volume).
- Started an ephemeral, non-dry-run container (`sigliere-mcp-livetest`)
  on port 8141, distinct from the persistent `sigliere-mcp.service`
  (still dry-run on 8140), so the managed service stayed untouched.
- Called `/healthz`, then `/set_frequency` for `rtlsdr-v4`.

### Results

- health endpoint: PASS — `{"ok":true,"role":"analyst","node_count":3,"dry_run":false}`
- set_frequency: **FAIL (HTTP 500)** — same underlying failure as the
  prior session, but now with a precise, stage-specific message instead
  of the old generic one.

### Captured Output

```text
{"detail":"radiod command failed on rtlsdr-v4 during tune (ssrc=1345155156). The channel was created/located but tune() never confirmed it landed on the requested frequency/preset; it may be left parked and will self-expire (~20s) if untouched. Retry, or raise the tune() timeout if this happens consistently on this node.: No status response received for SSRC 1345155156 within 5.0s"}
```

`journalctl -u radiod@rtlsdr-v4 -f` during the attempt:

```text
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439634]: Established under name 'sovereign-sigint RTL-SDR ad hoc single-frequency tasking'
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439635]: Established under name 'rtlsdr-v4-pcm.local'
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439637]: Established under name 'rtlsdr-adhoc-status.local'
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439641]: Established under name 'rtlsdr-adhoc-pcm.local'
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439640]: Established under name 'rubberduck ad-hoc'
Aug 06 01:25:22 rubberduck radiod@rtlsdr-v4[1439636]: Established under name 'sovereign-sigint RTL-SDR ad hoc single-frequency tasking'
Aug 06 01:25:44 rubberduck radiod@rtlsdr-v4[1439615]: start_demod: ssrc 1,345,155,156, output rtlsdr-v4-pcm.local, demod 1, freq 0.000, preset fm, filter (-8,000,+8,000)
Aug 06 01:25:44 rubberduck radiod@rtlsdr-v4[1439615]: dynamically started ssrc 1,345,155,156
Aug 06 01:26:21 rubberduck radiod@rtlsdr-v4[1439615]: CPU usage: 1.0% since start, 1.0% in last 60.9 sec
Aug 06 01:27:21 rubberduck radiod@rtlsdr-v4[1439615]: CPU usage: 0.9% since start, 0.8% in last 60.0 sec
Aug 06 01:28:21 rubberduck radiod@rtlsdr-v4[1439615]: CPU usage: 0.9% since start, 0.8% in last 60.0 sec
```

**Note:** whether the `-v -v` verbose override from the prior session's
investigation was active for this run is unconfirmed — the log doesn't
show the extra per-command noise that override was expected to add
beyond what's shown here. Treat the log above as standard verbosity
unless/until confirmed otherwise; don't assume verbose logging was on.

### Interpretation

- **The fix did what it was built to do.** The error now correctly
  identifies the `tune` stage and includes the `ssrc`, matching the
  root cause already isolated in the prior session (channel allocation
  via `ensure_channel`/`create_channel` succeeds; the subsequent
  `tune()` confirmation wait times out). This is a real improvement in
  diagnosability, not a guess — same SSRC (`1345155156`) as every prior
  attempt, same failure point, now stated explicitly instead of via a
  generic message.
- **The underlying live action is still blocked**, as expected — this
  fix deliberately did not touch the 5.0s timeout or the network path
  (see commit message). No new remediation for the live path was
  attempted this round.
- **New lead, not yet confirmed:** the journal shows no second log line
  of any kind for SSRC `1,345,155,156` after its creation at
  `01:25:44`, across three full CPU-usage heartbeat cycles (well past
  both the 5s `tune()` timeout and the ~20s self-expire window). The
  prior session's packet capture only confirmed the *first* command
  (`create_channel`) left the host and was acted on; nobody has yet
  captured whether the *second* command (`tune()`) leaves the host at
  all. This is a different, narrower question than "is the reply lost"
  — it's "was the request even sent/received" — and needs its own
  packet capture to resolve, not an assumption either way.

### Required Remediation (operator action, needs root)

1. **Cheap test, per the original remediation plan:** retry with a
   longer client-side `tune()` timeout to rule out pure latency vs. a
   reply (or request) that never arrives at all. Not yet wired as a
   configurable parameter in `radiod_adapter.py`/`operator_cli.py` —
   needs either a quick manual Python invocation against the container
   or a follow-up change to expose it.
2. **Packet capture specifically on the retune, not just creation:**
   `sudo tcpdump -i any -n udp port 5006 -c 40` while re-firing
   `set_frequency`, isolating whether a second command packet leaves
   the host after the creation packet, and whether radiod's control
   port ever receives it.
3. Continue requiring the full round trip (creation *and* a confirmed
   tune to the requested frequency) before calling `rtlsdr-v4` PASS —
   this retest does not clear that bar.

### Housekeeping

- Ephemeral `sigliere-mcp-livetest` container on port 8141 was used for
  this retest, kept separate from the persistent `sigliere-mcp.service`
  (dry-run, port 8140), which was left untouched.
