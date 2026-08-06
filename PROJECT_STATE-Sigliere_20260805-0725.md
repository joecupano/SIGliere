# Sigliere — Project State

**Purpose of this file.** Handoff document for a new chat. Read this to
bootstrap; do not re-derive it from conversation. Supersedes
`PROJECT_STATE-Sigliere_20260805-0215.md`. Repo:
`github.com/joecupano/sigliere`.

## What this is

A local-hardware SIGINT platform, single Ubuntu 24.04 LTS Server box.
HF/VHF/UHF signal capture + 802.11 device capture,
exposed to a local LLM through in-process native tools. Zero cloud
dependency.

## Architecture (fixed — do not revisit lightly)

Five-tier stack: **HMI** (Open WebUI :8080, OpenWebRX+ :8073, Caddy) →
**Cognitive** (Ollama, qwen3:14b default) → **Bridge** (producer
scripts, ingest pipeline, DB layer) → **DSP** (radiod, direwolf,
multimon-ng, kismet) → **OS** (Ubuntu 24.04, rootless Podman/Quadlet).
Hardware: RX-888 MkII (HF), HackRF One (VHF/UHF), RTL-SDR (RTL2832U +
R820T, ad hoc single-frequency), MT7612U (WiFi), i9 + RTX 5060 Ti.

**Data sinks:** `db/occupancy.db` (RF sightings, radiod-driven) →
`latest.kismet` (WiFi/BT, separate schema, 15-min refresh) → sigid
mirror (weekly) → `/data/audio` (4h ingest + on-demand whisper).

**LLM interface:** four native in-process Open WebUI tools —
occupancy, kismet, sigid_reference, whisper. In-process Python, not
MCP/HTTP. LLM is the correlation engine; no schema merging at DB layer.

**Radiod instances (systemd, `radiod@<instance>.service`):**
- `rx888-hf` — RX-888 MkII, HF, fixed channel list (WWV beacons + ham
  bands), active/running.
- `hackrf-2m` — HackRF One, 2m VHF, fixed channel list, active/running.
  (`mcp-server/config/nodes.json` calls this node `hackrf-vhf-uhf`.)
- `rtlsdr-v4` — RTL-SDR, ad hoc single-frequency tasking, `freq=0`
  dynamic/prototype channel only (no fixed list by design — see conf
  header in `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf`). Deployed and
  running as of this session; **live tasking is broken**, see below.

## MCP server — current state (this session's main work)

`mcp-server/` exposes `healthz`, `nodes`, `route_frequency`,
`radiod_status`, `set_frequency` over HTTP, roles `analyst`
(read-only) and `operator` (can call `set_frequency`), backed by
`ka9q-python`'s `RadiodControl`. Managed as `sigliere-mcp.service`
(Podman Quadlet, `~/.config/containers/systemd/`), currently running in
**dry-run mode** (`SIGLIERE_MCP_DRY_RUN=true`) — this is deliberate and
should stay the default until every node's live path is proven, per
this repo's fail-loud discipline.

**Live (non-dry-run) `set_frequency` status per node**, full evidence
trail in `docs/mcp-validation-evidence.md`:

| Node | Live test | Notes |
|---|---|---|
| `rx888-hf` | **PASS** | 7.100 MHz USB, dynamically created a channel with no prior fixed-list match. |
| `hackrf-vhf-uhf` | **PASS** | 146.520 MHz NFM, retasked an existing fixed channel. |
| `rtlsdr-v4` | **FAIL, root cause found, not yet fixed** | See below. |

### `rtlsdr-v4`: root cause identified, fix not yet applied

Eight live-fire attempts this session, all identical failure:
`radiod command failed: No status response received for SSRC
1345155156 within 5.0s`. Investigation ruled out, in order: networking
(packets confirmed on the wire, IGMP group properly joined),
freq=0/prototype-tasking semantics (radiod does dynamically create a
channel on request — confirmed via verbose log), and RTL-SDR/PLL
hardware (radiod never reaches a retune step).

**Actual root cause**, confirmed via `-v -v` radiod log during a live
attempt: `mcp-server/src/radiod_adapter.py`'s `set_frequency()` flow is
`_ensure_ssrc()` (creates the channel) then a separate `control.tune()`
(sets the real frequency). `create_channel()` succeeds server-side —
radiod logs `dynamically started ssrc 1,345,155,156` — but its own
confirmation reply doesn't reach the client within 5s. Unlike the
`ensure_channel()` branch just above it, the `create_channel()`
fallback branch in `_ensure_ssrc()` has **no `try/except`**, so the
`TimeoutError` propagates uncaught and `control.tune()` — the call that
would actually set 146.520 MHz — never runs. The channel is left
parked at `freq 0.000` and self-expires ~20s later (no persistent
residue, but also no successful control action).

**Next step (code fix, not another live test):** in
`radiod_adapter.py`, either wrap `create_channel()`'s branch in the
same `try/except` as `ensure_channel()` (fail loud with a specific
message instead of an uncaught propagation), or first try raising the
client-side confirmation timeout (cheaper test — tells us if this is
pure latency or a reply that never comes). Re-run the live test after
either change and require the full round trip (creation *and* tune) to
land on the requested frequency, not just channel creation.

**Also fixed this session, don't re-litigate:**
- Stale claim in `radiod@rtlsdr-adhoc.conf`'s header that RTL-SDR needs
  a companion `rtlsdrd` daemon — false, corrected in-file. `radiod`
  drives RTL-SDR directly via its own `rtlsdr.so`, no daemon needed.
- Stale claim that `radiod -I <conf>` validates a config file — this
  build's `radiod` doesn't have an `-I` flag at all (`getopt` string is
  only `"N:vV"`); usage banner is wrong. No config-validate mode
  exists; starting the service is the only way to exercise a conf.
- `mcp-server/config/nodes.json`'s `rtlsdr-v4` entry now has an
  explicit `status_address` (`239.234.164.106`), matching the same
  avahi-dependency remediation already applied to the other two nodes.

## Key decisions (baked in)
- Information on prior sessions is documented in the commits.
- Open WebUI roles **analyst** / **operator** are drafted
  (`mcp-server/openwebui-role-prompts.md` has the four provisioning
  prompts: create analyst read-only, create operator full-access,
  assignment policy, token handling policy) but **not yet applied** —
  no evidence file confirms these were run against the live Open WebUI
  instance. This is the next open item once `rtlsdr-v4` is fixed.
- **analyst** can use data from SDRs (read-only MCP tools).
- **operator** can use data from SDRs and make changes to SDRs
  (`mcp_set_frequency` included).
- MCP live-control validation is real evidence, not paraphrased —
  2 of 3 nodes proven end-to-end live; the third has a specific,
  understood, unfixed bug (above), not an unknown.
- `docs/mcp-validation-evidence.md` mcp.env token placeholders at
  `/home/baldrick/.config/sigliere/mcp.env` still need replacing with
  real values before production use — flagged, not done.

## Guardrails for future changes

1. **Verify against the repo/box, don't paraphrase or invent** — AST
   introspection, `find`, `systemctl`, config dry-run loads, packet
   capture, source-code grep when docs/comments are suspect (this
   session found and corrected two stale claims baked into a config
   file's own comments — don't trust prior comments at face value
   either). Keep flagging "unconfirmed" rather than assume.
2. **Bank fixes fail-loud with a specific fix command**, not silent
   auto-repair. (The `rtlsdr-v4` bug itself is an example of this
   guardrail being violated in existing code — `create_channel()`'s
   branch swallows nothing but propagates an unhelpful generic
   timeout with no operator-facing remediation hint; the fix should
   follow this guardrail, not just patch the symptom.)
3. **Preserve DB schema separation** — Kismet/Bluetooth device-identity
   data stays out of `occupancy.db`.
4. **Never invent frequencies, callsigns, MACs, config parameter names,
   or CLI syntax.** If unconfirmed, say so in the file, don't guess.
5. **Public-safe defaults only** in shared examples: callsign `N0CALL`,
   grid `FN30as`, city New York NY, tz `America/New_York`.
6. **Never commit secrets.**
7. Credentials (tokens, passwords) are never entered in chat — pushing
   to GitHub, and any `sudo`/root action, requires the operator's own
   authenticated session at their own terminal. This session confirmed
   the boundary in practice: the agent has no TTY/askpass and will not
   accept a password even if offered in chat; the working pattern is
   the operator runs privileged commands themselves and pastes output
   back, or grants a narrowly-scoped `NOPASSWD` sudoers rule for
   specific commands.

## Files touched this session, uncommitted as of this writing

- `docs/mcp-validation-evidence.md` — full `rtlsdr-v4` investigation
  trail (multiple dated entries).
- `ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf` — corrected stale
  `rtlsdrd`/`-I` claims in header comments, added deployment note.
- `mcp-server/config/nodes.json` — added `rtlsdr-v4` `status_address`.
- `/etc/radio/radiod@rtlsdr-v4.conf` — deployed on the host (not a
  repo file), content identical to `radiod@rtlsdr-adhoc.conf`.

Check `git status`/`git diff` before assuming these are still
uncommitted — confirm current state, don't trust this table.
