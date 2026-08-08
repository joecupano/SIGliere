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

## 2026-08-06 rtlsdr-v4: Extended-Timeout Diagnostic + Targeted Packet Capture

- Timestamp (host local, from journalctl): 2026-08-06T01:38:53–01:44:00
- Branch: main
- Commit: `64168c4`
- Scope: two of the follow-ups queued by the retest above — (1) confirm
  whether raising the client-side `tune()` timeout alone resolves the
  failure, (2) packet capture targeting the retune command specifically,
  not just channel creation. Both run via a standalone script
  (`/tmp/rtlsdr_tune_diag.py`, not committed) calling `ka9q-python`
  directly, bypassing the MCP HTTP/container layer entirely, against a
  freshly restarted `radiod@rtlsdr-v4` with `-v -v` confirmed active
  (unconfirmed in the prior retest).

### Setup

- `radiod@rtlsdr-v4` restarted with a `--runtime` `-v -v` override,
  confirmed active this time via the journal's verbose startup banner.
- `sudo tcpdump -i any -n host 239.234.164.106 -c 80 -w
  /tmp/rtlsdr-v4-retune-capture.pcap` running concurrently.
- Diagnostic: `ensure_channel(freq=146.520 MHz, preset=nfm, timeout=5.0)`
  → on failure, `create_channel()` fallback → `tune(ssrc=..., timeout=15.0)`
  (extended from the adapter's hardcoded 5.0s).

### Result 1: Extended Timeout Does Not Help

```text
[+0.000s] calling ensure_channel(freq=146520000.0, preset=nfm)...
[+6.002s] ensure_channel FAILED: Channel SSRC 1345155156 not verified within 5.0s. Requested: 146.520 MHz, nfm, 16000 Hz
[+6.002s] create_channel returned ssrc=1345155156
[+6.002s] calling tune(ssrc=1345155156, timeout=15.0)...
[+21.003s] tune() FAILED even with 15.0s timeout: No status response received for SSRC 1345155156 within 15.0s
```

**Conclusion: raising the timeout from 5s to 15s made no difference.**
This rules out pure latency (a reply that's merely slow) as the
explanation — waited 3x longer, still nothing.

### Result 2: Targeted Packet Capture

`tcpdump -r /tmp/rtlsdr-v4-retune-capture.pcap -n`:

```text
01:43:40.382648 eno1  Out IP 192.168.173.65.5006 > 239.234.164.106.5006: UDP, length 14
01:43:40.382740 lo    In  IP 127.0.0.1.33693 > 239.234.164.106.5006: UDP, length 305
01:43:40.958763 eno1  Out IP 192.168.173.65.5006 > 239.234.164.106.5006: UDP, length 14
01:43:41.383332 eno1  Out IP 192.168.173.65.39224 > 239.234.164.106.5006: UDP, length 40
01:43:41.383599 eno1  Out IP 192.168.173.65.5006 > 239.234.164.106.5006: UDP, length 14
... (repeated 192.168.173.65.39224 > 239.234.164.106.5006 outbound packets,
     roughly every 1-1.5s, through 01:44:00.463729) ...
```

Full capture and journal cross-referenced against the `radiod` log for
the same window:

```text
Aug 06 01:43:40 rubberduck radiod@rtlsdr-v4[1447076]: start_demod: ssrc 1,345,155,156, output rtlsdr-v4-pcm.local, demod 1, freq 0.000, preset fm, filter (-8,000,+8,000)
Aug 06 01:43:40 rubberduck radiod@rtlsdr-v4[1447076]: dynamically started ssrc 1,345,155,156
Aug 06 01:43:54 rubberduck radiod@rtlsdr-v4[1447076]: CPU usage: 0.7% since start, 0.7% in last 60.0 sec
```
(no further log lines for this SSRC, even with `-v -v` confirmed active)

**Conclusions:**

1. **Our commands genuinely leave the host, repeatedly** — outbound
   packets on port 39224 roughly every 1-1.5s for the full ~20s window.
   This rules out "the command isn't being sent" as an explanation.
2. **Exactly one inbound packet arrived in the entire capture** — at
   `01:43:40.382740`, on loopback, coincident with `dynamically started
   ssrc 1,345,155,156` in the radiod log. This is radiod's one-time
   creation announcement, not a reply to any later command. After it:
   **zero** inbound traffic for the rest of the ~20s window, despite a
   dozen-plus outbound retries.
3. This reproduces and sharpens the 2026-08-05 "Root Cause Isolated"
   entry's own capture finding (also zero inbound replies in a clean
   20s window) — now with confirmation that requests keep leaving
   throughout that window and still get nothing back, not just once.

### Correction to Prior Session's Working Hypothesis

The same diagnostic run printed client-side warnings —
`Radiod reporting TTL=0 for SSRC 1677018585/2500/5000/14074: Multicast
data restricted to localhost loopback only!` — repeated dozens of
times, which the immediately preceding chat turn floated as a possible
"noisy status channel" explanation. **That lead does not hold up:**
none of that traffic appears anywhere in this capture, which was
filtered to `host 239.234.164.106` (rtlsdr-v4's own status/control
group). Whatever is generating those warnings is not on this node's
status channel — most likely a shared/cached listener in `ka9q-python`
picking up other radiod instances' broadcasts (`rx888-hf`,
`hackrf-vhf-uhf`) or stale in-library state. Flagging this explicitly
so a future session doesn't re-chase it as a live lead without first
confirming it's actually sourced from `rtlsdr-v4`.

### Working Hypothesis (Not Confirmed)

`rtlsdr-v4` runs a single, currently idle/non-demodulating ad-hoc
channel (parked at `freq 0.000`, `[R82XX] PLL not locked!` warnings
seen at startup) — unlike `rx888-hf`'s 15+ constantly-churning fixed
channels. If radiod's status re-broadcast for a channel is tied to
active demodulator output rather than a fixed timer, an idle channel
here may simply never produce a second status broadcast at all,
regardless of client timeout — a structural gap for this specific
node's usage pattern, not a transient network or latency issue. This
is a hypothesis pending confirmation against `ka9q-radio`'s actual
status-broadcast trigger logic (`/opt/sovereign-sigint/src/ka9q-radio`
on this host) or a test with the native `control` CLI in place of
`ka9q-python`, to isolate a library-level bug from radiod's own
behavior. Do not act on this without verifying further.

### Required Remediation / Next Steps

1. Test with radiod's own native `control` CLI directly (bypassing
   `ka9q-python` entirely) against the same SSRC/frequency, to isolate
   whether this is a `ka9q-python`-specific gap or genuine radiod
   behavior. **The exact `control` invocation syntax is unconfirmed on
   this build** (flagged in `radiod@rtlsdr-adhoc.conf`'s own header and
   `README.md`) — do not guess it; derive it from `control --help` or
   the installed `ka9q-radio` source (`/opt/sovereign-sigint/src/ka9q-radio`)
   before running it.
2. If the native `control` CLI reproduces the same silence, escalate to
   `ka9q-radio` upstream (or its source) to understand the intended
   status-broadcast trigger for an idle/newly-created ad-hoc channel.
3. If the native `control` CLI succeeds where `ka9q-python` doesn't,
   this narrows to a `ka9q-python` library bug specific to idle-channel
   verification, reportable upstream with this evidence.

### Housekeeping

- `/tmp/rtlsdr_tune_diag.py` and `/tmp/rtlsdr-v4-retune-capture.pcap`
  are host-local scratch files, not committed to the repo.
- The `-v -v` runtime override from this session lives at
  `/run/systemd/system/radiod@rtlsdr-v4.service.d/override.conf` and
  does not survive a reboot (same as the prior session's).

## 2026-08-06 rtlsdr-v4 Root Cause: freq=0 Bootstrap Trap in `radiod` Itself

- Timestamp (host local): 2026-08-06T02:06:54–02:21:28 (native `control`
  TUI testing) plus source review immediately following
- Branch: main
- Scope: follow-up to the queued "test with the native `control` CLI"
  remediation item above. Ended up isolating the actual root cause via
  the reference `control` tool plus direct reading of the installed
  `ka9q-radio` source (`/opt/sovereign-sigint/src/ka9q-radio/src/`,
  the tree this host's `radiod`/`control` were built from), rather than
  a clean pass/fail from the tool itself.

### Native `control` Tool: Inconclusive as a Direct Comparison

Selected the `rtlsdr-adhoc-status.local` instance, entered SSRC `1`,
set Carrier to `145,250,000` via the `f` command (confirmed via source
at `control.c:925` — `getentry("Carrier frequency: ", ...)`, one
`sendto()` per keystroke, no batching). A targeted capture confirmed
the command packet actually left the host (a 24-byte outbound packet
distinct from the tool's routine 14-byte polls), but **zero** inbound
replies arrived for the entire session — not even to the routine
polls. Journal showed no `dynamically started ssrc` line at all for
this session, unlike every `ka9q-python` attempt. This means the
native-tool session diverged at an *earlier* step than the
`ka9q-python` tests did (channel creation itself, not just the
follow-up tune) — not a clean apples-to-apples comparison, and not
conclusive on its own. Recorded so a future session doesn't re-run
this exact test expecting a clean isolation result from it alone.

### Source Trace: The Actual Mechanism

`radio_status.c`'s command dispatcher (`radio_status()`) has two
completely different paths depending on whether the target SSRC
already exists:

- **New SSRC** (`lookup_chan()` returns NULL): `create_chan()` →
  `decode_radio_commands()` (applies the packet's fields) →
  **`send_radio_status()` called synchronously, immediately** →
  `start_demod()` → `dynamically started ssrc` logged if `Verbose`.
  Guaranteed reply.
- **Existing SSRC** (`lookup_chan()` finds it): the command is only
  **queued** (`chan->status.command = cmd`) for the channel's own
  per-block processing loop to pick up later. **No `send_radio_status()`
  call anywhere in this branch.** Worse: if a previous command is
  already queued and unprocessed, the new one is silently dropped
  (`// An entry already exists. Drop ours, until we make this a
  queue`) — no log, no reply, no error.

The queue is drained in `radio.c`'s `downconvert()` (`radio.c:1358`
region), called once per processing block for that channel. Critically,
**the very top of that function**, before the command-queue check,
is:

```c
if(chan->tune.freq == 0 && chan->lifetime > 0){
  if(--chan->lifetime <= 0){
    chan->demod_type = -1;  // No demodulator
    ...
    return -1; // terminate needed
  }
}
// Process any commands and return status
...
if(chan->status.command != NULL){
  restart_needed = decode_radio_commands(chan,chan->status.command,chan->status.length);
  send_radio_status(&Frontend.metadata_dest_socket,&Frontend,chan); // Send status in response
  ...
}
```

(`Template.lifetime = DEFAULT_LIFETIME * 1000 / Blocktime; // If freq
== 0, goes away 20 sec after last command`, `radio.c:383`.)

So: a channel parked at `freq==0` is on a countdown to self-destruct,
and that countdown check runs **before** the code that would process
a queued command and reply to it, every single call. If the queued
command that would move the channel off `freq==0` never gets a chance
to run before the channel is torn down (or, more precisely per the
finding below, never gets a chance to run *at all*), it dies
unprocessed and unacknowledged.

### Why the Channel Never Gets a Chance: RTL-SDR's Tuning Floor

Every creation event in this investigation, across every tool, logged
`freq 0.000` at `start_demod` — the channel is *born* at `freq=0`, an
explicit "prototype" placeholder meant to be retuned by a second,
separate command. But `mcp-server/config/nodes.json` declares
`"min_hz": 24000000` for `rtlsdr-v4` — **0 Hz is below this hardware's
real tunable floor.** Every single radiod startup for this instance
has logged `[R82XX] PLL not locked!` and fallen back to `RTL freq
28,800,000, tuner freq 28,800,000` — consistent with the RTL2832U/R820T
tuner simply being unable to lock at the frequency the prototype
channel starts at. The native `control` TUI's Signal panel stayed at
`-inf`/`nan` across every field (Input, A/D, S/N, Output) for the
entire session — consistent with this channel never having real
samples flow through it at all, from creation onward.

Put together: the ad-hoc conf's `freq=0` prototype pattern creates a
channel at a frequency this hardware cannot actually tune to. If that
prevents (or sufficiently delays) the channel's own per-block
processing from running normally, the queued follow-up command that
would move it to a real, receivable frequency never gets applied or
acknowledged — independent of which client tool sent it, independent
of timeout length. This is consistent with every result gathered
across this entire investigation: `ka9q-python` at 5s and 15s timeouts,
the native `control` tool, packet captures showing commands reliably
leaving the host, and journal logs showing exactly one reply (at
creation, `freq=0`) and silence thereafter in every case.

### Why `rx888-hf` / `hackrf-vhf-uhf` Never Hit This

Neither prior PASS test ever bootstrapped a channel starting at an
out-of-range frequency: `hackrf-vhf-uhf`'s test retasked an
already-tuned, already-running fixed channel (never at `freq=0` to
begin with), and `rx888-hf` is an HF/6m receiver with no comparable
tuning floor near DC. The `freq==0`-at-birth pattern is specific to
`rtlsdr-v4`'s ad-hoc, no-fixed-channel-list design.

### Status: Likely Root Cause Found, Not Yet a Confirmed Fix

This is the most complete explanation gathered so far and is
consistent with every piece of evidence collected across this whole
investigation, but two things remain unconfirmed:

1. Direct proof that `downconvert()` isn't running (or isn't running
   normally) for this channel while parked at `freq=0` — inferred from
   the Signal panel staying at `-inf`/`nan` and the consistent
   `chan->lifetime` framing, not directly observed via a debugger or
   added instrumentation.
2. Whether `chan->lifetime` gets refreshed anywhere on receipt of a
   command (the `radio.c:383` comment implies "20 sec after last
   command," but no explicit `chan->lifetime = ...` reset was found in
   the reviewed sections) — if it does reset on queueing rather than
   only on successful processing, the exact failure mechanics differ
   slightly from what's described above even though the outcome is the
   same.

### Suggested Remediation Direction (Not Yet Applied)

The likely fix belongs in `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf`
or radiod's own Template handling, not in `mcp-server`: don't let the
ad-hoc prototype channel default to `freq=0` given this hardware's
`min_hz` floor. Possible directions, none applied or validated yet:

1. Give the ad-hoc Template a default frequency inside the hardware's
   valid range (e.g., the tuner's own fallback of `28,800,000` Hz)
   instead of `0`, so a freshly created channel is never parked
   somewhere the hardware can't lock to.
2. If `radiod` itself requires `freq=0` as the literal "unconfigured"
   sentinel for this dynamic-channel pattern, the fix likely needs to
   happen upstream in `ka9q-radio` (the lifetime-check-before-command-
   processing ordering in `downconvert()`, or making channel creation
   atomic with the first real frequency rather than a two-step
   create-then-tune sequence) — outside what this repo controls.
3. Do not attempt a client-side (`mcp-server`) workaround (e.g., just
   raising the timeout further) without validating one of the above —
   the evidence here indicates the channel may never get a chance to
   process the command at all, not that it's merely slow.

### Housekeeping

- Source references are to
  `/opt/sovereign-sigint/src/ka9q-radio/src/{radio_status.c,radio.c,control.c}`
  on this host — the build this instance's `radiod`/`control` binaries
  were compiled from. Line numbers are as of this session; re-verify
  if the source tree is updated.

## 2026-08-06 rtlsdr-v4: Conf Fix Tested — Fixes Boot Channel Only, Not `set_frequency`

- Timestamp (host local): 2026-08-06T02:47:49–02:56:xx
- Branch: main
- Commit under test: `0da969f` ("rtlsdr-v4: give [AD-HOC] a real
  starting freq instead of 0")
- Scope: deploy and live-test the remediation from the prior root-cause
  entry — does giving `[AD-HOC]` a real starting frequency (`24920000`
  instead of `0`) fix live retasking?

### Deployment

```bash
sudo cp ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf /etc/radio/radiod@rtlsdr-v4.conf
sudo systemctl restart radiod@rtlsdr-v4
```

### Result 1: The Pre-Declared Boot Channel — Fixed

```text
Aug 06 02:47:50 rubberduck radiod@rtlsdr-v4[1482807]: start_demod: ssrc 24,920, output rtlsdr-adhoc-pcm.local, demod 1, freq 24,920,000.000, preset fm, filter (-8,000,+8,000)
Aug 06 02:47:50 rubberduck radiod@rtlsdr-v4[1482807]: [ad-hoc] 1 channels started
```

The channel radiod auto-starts at boot (`ssrc` auto-derived as
`24920`, matching the frequency in kHz — apparently radiod's own SSRC
convention for config-declared channels without an explicit `ssrc=`)
now comes up at the real, in-range frequency, not `0`. This part of
the fix worked exactly as intended, confirming the freq=0/hardware
tuning-floor mechanism was real for this specific case.

### Result 2: Fresh Dynamic Channel Creation (the actual `set_frequency` path) — Still Fails

Moments after the restart, unrelated stray traffic (see Housekeeping —
an hour-old leaked `sigliere-mcp-livetest` container never cleaned up
from an earlier session) created ANOTHER dynamic channel, at `freq
0.000`, same as always — initially confusing, since it looked like
fresh evidence but wasn't. After clearing that container and running a
**genuinely fresh, controlled test** — a frequency never used all
session (`147.000 MHz`, `nfm`) via a new ephemeral container
(`sigliere-mcp-livetest2`) — the result was unambiguous:

```text
Aug 06 02:54:27 rubberduck radiod@rtlsdr-v4[1482807]: start_demod: ssrc 1,422,605,731, output rtlsdr-v4-pcm.local, demod 1, freq 0.000, preset fm, filter (-8,000,+8,000)
Aug 06 02:54:27 rubberduck radiod@rtlsdr-v4[1482807]: dynamically started ssrc 1,422,605,731
```

```text
{"detail":"radiod command failed on rtlsdr-v4 during tune (ssrc=1422605731). The channel was created/located but tune() never confirmed it landed on the requested frequency/preset; it may be left parked and will self-expire (~20s) if untouched. Retry, or raise the tune() timeout if this happens consistently on this node.: No status response received for SSRC 1422605731 within 5.0s"}
```

Same failure shape as every test before the conf change: fresh SSRC,
`freq 0.000` at creation, one reply, then silence; `tune()` times out
identically at 5.0s.

### Interpretation

**The conf change fixes only the one pre-declared, boot-time channel
— it does not fix the actual `set_frequency` code path.** That path
(`mcp-server/src/radiod_adapter.py`'s `_ensure_ssrc()`, via
`ensure_channel()`/`create_channel()`) always creates a brand-new
dynamic channel per request, using a deterministically-allocated SSRC
computed from the request parameters — never the config-declared
`ssrc=24920` channel. That dynamic-creation path still bootstraps new
channels at `freq=0` regardless of what `[AD-HOC]`'s own `freq=` value
says, meaning radiod's internal dynamic-channel `Template` (used for
genuinely new SSRCs, as opposed to the channel actually declared and
parsed from the conf file) is evidently independent of the conf's
per-channel `freq=` setting. The freq=0 root-cause mechanism from the
prior entry is still consistent with everything observed here — this
result narrows *where* the fix needs to apply, not whether the
mechanism is real.

### Not Yet Tried: Retasking the Now-Healthy Boot Channel Directly

One scenario the root-cause theory directly predicts should work and
hasn't been tested yet: issuing a `tune()` against the **existing**
`ssrc=24920` channel (alive, receiving real samples, not stuck at
`freq=0`) instead of letting the adapter create a new dynamic SSRC.
If that succeeds cleanly, it would further confirm the freq=0
bootstrap mechanism and point toward a `mcp-server`-side fix (special-
case `rtlsdr-v4` to retask the known boot-time SSRC rather than
dynamically creating a new one) as a viable near-term workaround, even
if the deeper radiod/`ka9q-radio` dynamic-`Template` behavior is never
changed upstream.

### Housekeeping

- Two leaked ephemeral containers found and removed this session:
  `sigliere-mcp-livetest` (from the "extended-timeout diagnostic"
  entry, left running for roughly an hour past when it should have
  been cleaned up) and `sigliere-mcp-livetest2` (this session's own,
  once testing was done). Confirm with `podman ps -a` before assuming
  no stray containers remain — this is the second time in this
  investigation cleanup was assumed done but wasn't.
- The persistent `sigliere-mcp.service` (dry-run) and the unrelated
  `caddy`/`open-webui` containers were left running throughout,
  untouched.

## 2026-08-06 rtlsdr-v4: Direct Retask of Boot Channel — CONFIRMED WORKING

- Timestamp (host local): 2026-08-06T03:01:44
- Branch: main
- Scope: test the "not yet tried" item from the prior entry — retask
  the already-alive boot-time channel (`ssrc=24920`) directly via
  `ka9q.RadiodControl.tune()`, bypassing `ensure_channel()`/
  `create_channel()` entirely, via a standalone script
  (`/tmp/rtlsdr_retask_boot_channel.py`, not committed).

### Result: Clean, Fast Success

```text
[+0.000s] calling tune(ssrc=24920, freq=147000000.0, timeout=5.0)...
[+0.053s] tune() OK: {'ssrc': 24920, 'command_tag': 1007401193, ...,
  'frequency': 147000000.0, 'preset': 'nfm', ...,
  'destination': {'family': 'IPv4', 'address': '239.152.12.134', 'port': 5004}, ...}
```

**0.053 seconds**, full real status response — not a 5s+ timeout.
Confirmed server-side too, radiod journal (verbose logging still
active from earlier in this investigation):

```text
Aug 06 03:01:44 rubberduck radiod@rtlsdr-v4[1482807]: command loadpreset(ssrc=24920) mode=nfm
Aug 06 03:01:44 rubberduck radiod@rtlsdr-v4[1482807]: set ssrc 24920 freq = 147,000,000.000
Aug 06 03:01:44 rubberduck radiod@rtlsdr-v4[1482807]: new filter for chan 24,920: IF=[-6,250,6,250], samprate 24,000, kaiser beta 11.0
```

### Conclusion

**Root cause and fix direction both fully confirmed.** Retasking a
channel that's already alive and receiving real samples works
cleanly and fast — the exact opposite of every dynamically-created
channel tested all day. This closes the investigation's central
question: the freq=0 bootstrap trap for brand-new dynamic channels on
this hardware is real, and retasking an already-existing channel is
the reliable path around it.

**Fix direction for `mcp-server`:** for `rtlsdr-v4` specifically,
`radiod_adapter.py`'s `set_frequency()` should retask the known
boot-time SSRC (`24920`) directly via `tune()`, instead of routing
through `_ensure_ssrc()`'s `ensure_channel()`/`create_channel()` path
that dynamically allocates a new SSRC per request. Implementation
tracked as a follow-up code change, not yet applied as of this entry.

## 2026-08-06 rtlsdr-v4: boot_ssrc Fix Implemented, Live-Tested, and a Second Gap Found

- Timestamp (host local): 2026-08-06T02:47:49–03:22:xx (spans conf
  deploy through the mode-change isolation test below)
- Branch: main
- Commits under test: `0da969f` (conf freq fix), `ec85ba2`
  (`boot_ssrc` adapter fix, before the mode-change guard added later
  in this same entry)

### Round 1: `boot_ssrc` Path Confirmed Working, But Live HTTP Test Failed — Race Condition, Not a Real Failure

First attempt through the actual MCP HTTP path (ephemeral container,
rebuilt image) failed with `during tune (ssrc=24920)` — but the error
correctly named the boot SSRC, confirming the code change itself was
exercised correctly (no dynamic channel created). Root cause of *this*
specific failure: my own test sequencing bundled `podman run -d` →
`curl` → `podman rm -f` with no wait, so `curl` hit the container
before Uvicorn had finished starting, then the container was killed
before a retried request could land. Flagged so a future session
doesn't misread this as evidence against the fix — it wasn't a fix
failure, it was a bad test script.

### Round 2: Mode-Change Confound

Once the container was confirmed healthy (`GET /healthz` 200), a
proper `set_frequency` call still failed the same way. Traced through
several steps (full detail: this was a live, multi-turn investigation)
to find the actual variable: **the request changed mode** (`nfm` →
`am`) in addition to frequency, on a channel whose boot preset is
`fm`. A same-mode-only follow-up also failed — but that was because
the *first* (mode-changing) request had already left the channel in a
bad state (a single-entry command queue server-side; see the earlier
root-cause entry's `radio_status.c` trace), not because same-mode
changes are broken.

### Round 3: Clean, Isolated Confirmation (Fresh Restart Each Time)

After `sudo systemctl restart radiod@rtlsdr-v4` (clean channel, back
to boot preset `fm` at `24,920,000 Hz`):

- **Same-mode (`nfm`), frequency-only retask, via the standalone
  script directly (no container):** `[+0.060s] tune() OK`, full status
  returned, confirmed in the journal (`set ssrc 24920 freq =
  146,500,000.000`). **Reliable.**
- **On that same still-healthy channel, immediately after, a
  mode-change-only request (`preset='am'`, same frequency):**
  `[+5.000s] tune() FAILED: No status response received for SSRC
  24920 within 5.0s` — and the journal shows **zero** log activity for
  this attempt, unlike the instant, logged success just before it.

This isolates it cleanly: **frequency changes within the same demod
family (fm/nfm/wfm) work reliably on the boot channel. A demod-type-
changing mode switch (into/out of the linear family: am/usb/lsb/cw/iq)
does not — same symptom as the original freq=0 bug (radiod never
replies), but a distinct, separate cause** (most likely tied to
`downconvert()`'s `restart_needed` handling for demod-type changes,
per the earlier source trace — not yet investigated further).

### Remediation Applied: Fail-Loud Guard, Not a Fix

The actual restart-path bug is not fixed (out of scope for this
session — would need another full source-trace investigation like the
freq=0 one). Instead, added a same-family check in
`radiod_adapter.py`'s `set_frequency()`: when a node declares both
`boot_ssrc` and `boot_mode`, a request whose mode would require a
different demod family than the boot mode is rejected immediately,
before any radiod command is sent, with a clear message pointing at
this entry rather than silently hanging for 5s like the underlying bug
does. `nodes.json`'s `rtlsdr-v4` entry now carries `"boot_mode": "fm"`
alongside `"boot_ssrc": 24920`.

Verified with mocks: `fm`/`nfm`/`wfm` requests pass through unaffected
(`tune()` invoked normally); `am`/`usb`/`lsb`/`cw` requests are
rejected before `RadiodControl` is even constructed; a node with no
`boot_mode` set (guard opt-out) is unaffected either way.

### Current Status of `rtlsdr-v4`

- Frequency retasking within the `fm` family: **working, confirmed
  live**, via the `boot_ssrc` fix.
- Mode changes across demod families: **blocked with a clear error**,
  not fixed. A caller requesting `am`/`usb`/`lsb`/`cw`/`iq` on this
  node gets an immediate, specific rejection instead of a 5s hang and
  an opaque timeout.
- Still not re-verified through the actual MCP HTTP path end-to-end
  after Round 1's race-condition-spoiled attempt — the standalone
  script tests in Round 3 are solid evidence the underlying fix works,
  but a clean HTTP-path retest (properly sequenced this time) would
  close that last gap.

### Housekeeping

- `/tmp/rtlsdr_retask_boot_channel.py` and
  `/tmp/rtlsdr_mode_change_test.py` are host-local scratch files, not
  committed to the repo.
- Multiple `radiod@rtlsdr-v4` restarts occurred through this entry's
  testing; the channel's state (frequency/mode) at any given moment
  should not be assumed from prior entries — check live if it matters.

## 2026-08-06 rtlsdr-v4: CORRECTION — Boot Channel Only Survives ONE Command Per Restart

- Timestamp (host local): 2026-08-06T03:31:38–03:36:23
- Branch: main
- Commit under test: `275e7b2` (mode-change guard)
- **This entry corrects the "CONFIRMED WORKING" framing of the two
  entries immediately above it.** Every prior success in this
  investigation — the standalone-script tests, and this entry's own
  first HTTP-path test — happened to be the *first* command sent to
  the boot channel after a radiod restart. Nobody had tested a third
  request in sequence until now. It fails.

### Method

Full end-to-end testing via the real MCP HTTP path this session (a
material change from every earlier entry: this was run directly by
the agent on `rubberduck`, not relayed through the operator — the
agent has full shell access on this box; earlier sessions' assumption
of a separate sandboxed environment was simply wrong, discovered only
at this point).

1. Fresh `sudo systemctl restart radiod@rtlsdr-v4` (operator-run, agent
   has no passwordless sudo — that boundary still holds).
2. Rebuilt `localhost/sigliere-mcp:latest` from `275e7b2`.
3. Ephemeral container, non-dry-run, health-checked before use.

### Results

| Request | Timing | Mode | Result |
|---|---|---|---|
| A (first after restart) | immediate | nfm | **PASS** — 0.089s, `status: applied`, journal shows clean `set ssrc 24920 freq = 145,000,000.000` |
| — (guard test) | immediate after A | am | **Correctly rejected**, 0.017s, client-side, zero radiod contact (confirmed via journal) |
| B (second real command) | 5s after A | nfm | **FAIL** — 5.0s timeout, `No status response received for SSRC 24920` |
| C | 25s after B (30s after A) | nfm | **FAIL** — identical timeout. Channel does not self-recover with time. |

The guard-rejected `am` request is confirmed *not* the cause of B's
failure — the journal shows zero new radiod activity for it, and B
failed anyway. Radiod's own process stayed healthy throughout (regular
`CPU usage` heartbeats every 60s) — this is one channel stuck, not the
whole instance.

### Root Cause (Source-Confirmed)

`radio.c`'s `demod_thread()` wraps whichever demod function
(`demod_fm()` etc.) in `while(status == 0){ status = demod_fm(p); ... }`
— comment: *"When a demod exits, the appropriate one is restarted,
which can be the same one if demod_type hasn't changed."* `demod_fm()`
(`fm.c`) returns `0` ("Normal exit") whenever its own inner
`while(downconvert(chan) == 0)` loop ends for *any* reason, including
`downconvert()` signaling `restart_needed` after processing a queued
command (not just fatal termination) — so the outer loop re-enters
`demod_fm()` from scratch: recreates filter buffers
(`create_filter_output`), resets the fine-tuning oscillator, resets
squelch state, everything. This matches the `new filter for chan
24,920: ...` log line appearing on every *successful* command, not
just mode changes — ordinary frequency retasking triggers this same
full restart.

**The critical line: `demod_fm()`'s very first executable statements
are `pthread_mutex_lock(&chan->status.lock); FREE(chan->status.command);`**
— unconditional, on every entry. If a new command arrives and gets
queued (`radio_status.c`'s existing-channel path) while the channel is
between demod-thread invocations — mid-restart, filters being
recreated — the next `demod_fm()` entry frees that queued command
before it is ever processed or replied to. The client waits the full
`tune()` timeout for a reply that was destroyed, not delayed.

This is consistent with every result in this investigation, including
the *original* freq=0 bug: a freshly created channel's first real tune
also triggers this restart cycle, on top of the freq==0 self-destruct
race already documented — compounding, not competing, explanations.
The other demod files (`linear.c:45`, `wfm.c:39`, `spectrum.c:34,202`)
were checked and show the identical `FREE(chan->status.command)`-at-entry
pattern (same grep as the original root-cause entry), so this is
unlikely to be FM-specific — plausibly affects any demod type on this
build.

### Practical Implication

**The `boot_ssrc` fix is real but much narrower than previously
stated: it reliably handles exactly one retask per `radiod@rtlsdr-v4`
restart, not repeated ad hoc tasking.** This falls well short of what
`radiod@rtlsdr-adhoc.conf`'s own design intends ("whatever single
frequency is of interest right now," implying operators retask this
node repeatedly over a session). A second `set_frequency` call against
this node will currently hang 5s and fail, with no self-recovery —
only a full service restart clears it, which needs root and briefly
interrupts anything using the channel.

### Status: Deeper Bug, Not Fixed This Session

This is a real `ka9q-radio` bug (or at minimum an unresolved footgun
in this codebase's restart/command-queue interaction), not something
fixable from `mcp-server`. Two honest paths forward, neither attempted
yet:

1. **Report upstream to `ka9q-radio`** with this evidence trail —
   `demod_fm()`'s unconditional `FREE(chan->status.command)` racing
   against a same-channel restart cycle looks like a genuine bug, not
   an intentional design choice, and would plausibly affect any radiod
   deployment doing live per-channel retasking, not just this ad hoc
   conf.
2. **Client-side mitigation (heavy-handed, not yet built):** have
   `mcp-server` issue `sudo systemctl restart radiod@rtlsdr-v4` before
   every `set_frequency` call to this node. Requires passwordless sudo
   for the service account (a real security/operational tradeoff to
   weigh deliberately, not a small ask) and briefly drops the channel
   entirely, so this is a real design decision, not a quick patch —
   do not implement without discussing the tradeoff explicitly.

Until one of those happens, `rtlsdr-v4` should be considered **PASS
for exactly one retask per restart, FAIL for repeated live tasking** —
a materially different, more limited status than "PASS" alongside
`rx888-hf`/`hackrf-vhf-uhf` implied in earlier entries.

### Housekeeping

- Cleaned up three leaked ephemeral containers found still running
  from earlier in this session (`sigliere-mcp-livetest2`,
  `-livetest3`, plus this entry's own `-livetest4`/`-livetest5`) —
  the fourth time in this investigation cleanup was missed. Worth
  treating as a real, recurring process gap: always run `podman ps -a`
  before concluding a session, not just after each individual test.

## 2026-08-06 rtlsdr-v4: DESCOPED from the AI/MCP Path — OpenWebRX+-Only Going Forward

- Decision recorded, not a test result.
- Given the one-command-per-restart limit above is a `ka9q-radio`
  source bug, not fixable from this repo, the operator decided:
  **RTL-SDR is OpenWebRX+-only. It will not be used in the AI/MCP
  path.**

### What changed

- `mcp-server/config/nodes.json`: the `rtlsdr-v4` node entry removed
  from the active `"nodes"` list. `GET /nodes`/`route_frequency` will
  no longer offer or route to it. `node_count` in health checks is now
  **2**, not 3 — don't be surprised by that relative to every earlier
  entry in this file.
- `radiod@rtlsdr-v4.service`: stopped and disabled on the host
  (operator-run), freeing the RTL-SDR for OpenWebRX+'s single-owner
  use per `scripts/sdr-mode.sh`'s rule.
- Upstream bug report drafted:
  [ka9q-radio-upstream-issue-command-queue.md](ka9q-radio-upstream-issue-command-queue.md)
  — not yet filed as of this entry (no `gh` CLI available on this
  host; needs the operator to submit via the GitHub web UI).
- `README.md`, `docs/MCP-server-design.md`, `scripts/sdr-mode.sh`
  updated to state the decision and point here.

### What was deliberately preserved, not deleted

Per explicit instruction — "save the work we have done with RTL-SDR
and radiod should radiod get patched":

- `mcp-server/src/radiod_adapter.py`'s `boot_ssrc`/`boot_mode` support
  — general-purpose, harmless for nodes that don't set them, and still
  correct for the "one retask per restart" case if this node is ever
  reactivated.
- `mcp-server/config/nodes.rtlsdr-v4.disabled.json` — the exact removed
  node block, ready to paste back into `nodes.json`'s `"nodes"` array,
  with a note to re-verify `boot_ssrc`/`boot_mode` against the conf
  file's state at that time before trusting them.
- `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf` — left with its
  freq=0→24920000 fix and full investigation history in comments;
  not reverted.
- This entire evidence log, unedited above this point.

### If picking this back up later

1. Check whether `ka9q-radio` upstream has addressed the command-queue
   bug (issue link once filed — check this file's git history / the
   issue draft for the eventual URL).
2. If so, re-verify against a fresh multi-command live test (not just
   one retask — that was exactly what earlier entries in this file got
   wrong) before restoring `rtlsdr-v4` to `nodes.json`.
3. `sudo systemctl enable --now radiod@rtlsdr-v4` and re-check
   single-owner conflicts with OpenWebRX+ before re-enabling.

## 2026-08-08 analyst/operator Open WebUI Role Provisioning — server-side ready, UI step still open

- Timestamp (UTC): 2026-08-08T02:14:08Z
- `sigliere-mcp.service`: active, running since 2026-08-06T04:45:11Z,
  `SIGLIERE_MCP_DRY_RUN=true` (unchanged, still the default per this
  repo's discipline).

### What was found already done (contradicts the 2026-08-05 handoff doc)

`PROJECT-STATE_20260805-2341.md` flagged `~/.config/sigliere/mcp.env`'s
`SIGLIERE_MCP_TOKENS_JSON` as still holding placeholder tokens. Checked
directly: it does not — both tokens are real, random, and were set
2026-08-05T05:19:53Z (before that handoff doc was even written). Confirmed
live rather than trusting either doc:

| Token role | `GET /healthz` | `POST /set_frequency` |
|---|---|---|
| analyst | 200 | **403** (`role analyst lacks operator permission`) |
| operator | 200 | **200** (dry-run, no hardware effect) |
| (none/invalid) | 401 | — |

This confirms the server-side role gate (`require_role`/`_mcp_auth` in
`mcp-server/src/sigliere_mcp_server.py`) already enforces the
analyst/operator boundary correctly and independently of anything done in
Open WebUI.

### What changed this session

- `scripts/openwebui-mcp-command.sh`: generalized to print **both**
  role-scoped connection blocks by default (was operator-only), each
  token looked up live from `SIGLIERE_MCP_TOKENS_JSON` rather than a
  second hardcoded env var. Fixed a latent bug this surfaced: `source`-ing
  the env file stripped the JSON's double quotes via bash word-splitting
  on the unquoted `VAR={"a":"b"}` line — now read via `grep`+`cut`
  instead, bypassing `source` for that one value. Verified all three
  invocation forms (no arg / `analyst` / `operator` / bad-arg usage error)
  against the live `mcp.env`.
- `mcp-server/openwebui-role-prompts.md`: rewritten from bare "prompts"
  text into a concrete, ordered procedure (register both connections →
  create both groups → scope access → assign users) plus the live
  403/200 evidence above, so a misconfigured Open WebUI step is now
  documented as a UX/exposure gap, not a safety hole.
- `mcp-server/README.md`: pointed its role-provisioning section at the
  rewritten doc instead of duplicating a shorter, now-stale sequence.

### What's still open — needs the operator, not this agent

Registering the two connections, creating the `analyst`/`operator`
groups, and scoping the operator connection to the `operator` group all
require an Open WebUI Admin Panel login. No credentials for that login
exist anywhere in this repo or its configs (checked), and none should be
stored there — this is the same "hand the operator the exact command"
boundary as `sudo`/`git push`, just for a web login instead of a shell
credential prompt. `mcp-server/openwebui-role-prompts.md` has the exact
steps and paste-ready connection blocks (`bash
scripts/openwebui-mcp-command.sh`) ready for the operator to run through.

## 2026-08-08 OpenAPI Tool Server Connection — CORS Bug Found and Fixed, Live Connection Confirmed

- Timestamp (UTC): 2026-08-08T03:41:29Z

### Symptom

Operator registered the MCP server (`:8140`) as an Open WebUI OpenAPI-type
connection (per `scripts/openwebui-mcp-openapi-command.sh`'s printed
values — `URL: http://192.168.173.65:8140`, `OpenAPI Spec URL:
http://192.168.173.65:8140/openapi.json`, `Auth: Bearer` + token) and got
**"Failed to connect to http://192.168.173.65:8140 OpenAPI tool server"**
from Open WebUI's UI on Save/Verify.

### Root cause (found by reading Open WebUI's own installed source, not guessed)

This build's "Verify"/spec-fetch for an OpenAPI-type tool server connection
runs as a **browser-side `fetch()` call straight to the tool server**, not
proxied through Open WebUI's own backend (contrary to this repo's earlier
assumption; `open_webui/routers/configs.py`'s `verify_tool_servers_config`
exists but was never hit — zero matching requests in Open WebUI's own
access log during two live reproduction attempts). The MCP server had no
CORS handling, so the browser's mandatory preflight `OPTIONS
/openapi.json` request hit FastAPI's default 405 and the browser aborted
before ever sending the real GET. Confirmed directly in the MCP server's
own log, correlated to the exact moment of each reproduction attempt:

```
192.168.73.65:xxxxx - "OPTIONS /openapi.json HTTP/1.1" 405 Method Not Allowed
```

— while every non-browser test against the same server (`curl` from the
box, `podman exec open-webui curl ...` from inside Open WebUI's own
container) succeeded throughout, which is what made this look like a
reachability problem at first. It wasn't; both `host.containers.internal`
and the LAN IP were always reachable. The one path never exercised until
this point was a real browser doing a CORS preflight.

### Fix

`mcp-server/src/sigliere_mcp_server.py`: added `CORSMiddleware`
(`allow_origins` from `SIGLIERE_MCP_CORS_ORIGINS`, default `*` — consistent
with this repo's existing single-operator/no-cloud-exposure trust model;
the real authorization boundary stays the per-request bearer token, which
CORS does not touch). Rebuilt `localhost/sigliere-mcp:latest`, restarted
`sigliere-mcp.service`.

### Verification (all live, dry-run mode unchanged)

| Check | Before | After |
|---|---|---|
| `OPTIONS /openapi.json` | 405 | **200** |
| `Access-Control-Allow-Origin` header present | no | **yes (`*`)** |
| `GET /healthz` no token | 401 | 401 (unchanged) |
| `GET /healthz` analyst token | 200 | 200 (unchanged) |
| `POST /set_frequency` analyst token | 403 | 403 (unchanged) |
| `POST /set_frequency` operator token | 200 (dry-run) | 200 (dry-run, unchanged) |

Operator confirmed the Open WebUI connection now saves/verifies
successfully. Role gating regression-tested clean — the fix only unblocks
the browser preflight, it changes nothing about who can call
`set_frequency`.
