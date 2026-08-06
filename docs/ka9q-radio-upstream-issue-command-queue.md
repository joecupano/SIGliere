# Upstream Issue Draft — ka9q-radio

**Status:** Drafted, not yet filed. File at
https://github.com/ka9q/ka9q-radio/issues/new once reviewed.

**Why this file exists:** this repo (Sigliere) found and worked around
the symptom from the client side (see
`docs/mcp-validation-evidence.md`'s `rtlsdr-v4` entries, and
`mcp-server/src/radiod_adapter.py`'s `boot_ssrc`/`boot_mode` handling),
but the actual defect lives in `radiod` itself. This is the writeup to
report it upstream. Kept in the repo so the investigation and its
evidence aren't lost even though Sigliere itself has moved RTL-SDR to
OpenWebRX+-only use and is no longer blocked on this being fixed.

---

## Title

A channel's queued status command can be silently dropped across a
demod restart, so a live-tasked channel only reliably accepts one
control command per restart

## Environment

- `radiod`/`control` built from this repo at commit `e1224dcd1991637ba8e1caa68cd802e1b22933de` (2025-11-07).
- Hardware: RTL-SDR (RTL2832U + Rafael Micro R820T), driven via the
  `rtlsdr.so` front-end plugin.
- Client tested: `ka9q-python`'s `RadiodControl.tune()`/
  `ensure_channel()`/`create_channel()`, and separately the bundled
  `control` TUI (both reproduce the core symptom, via slightly
  different paths — see below).

## Summary

A channel that already exists (created either by the conf file or
dynamically) can only reliably process **one** live control command.
A second command sent afterward — even identical in shape to the
first, even with 5–30+ seconds of spacing, even on a channel that is
demonstrably alive and healthy — gets no reply and the channel does
not recover on its own. Only restarting the whole `radiod` instance
clears it. This appears to be caused by `demod_fm()` (and the
equivalent in `linear.c`/`wfm.c`/`spectrum.c`) unconditionally freeing
`chan->status.command` at the top of every entry, combined with
`demod_thread()` fully re-entering the demod function from scratch
whenever `downconvert()` reports `restart_needed` — which ordinary
frequency changes appear to trigger, not just demod-type changes.

## Two reproduction scenarios, same underlying mechanism

### Scenario A — a freshly created dynamic channel never gets its first real tune applied

Config: a channel section with `freq = 0`, radiod's own documented
"prototype" sentinel for a dormant channel meant to be tasked live
against an unused SSRC.

1. Client calls `ensure_channel()`/`create_channel()`-equivalent for a
   new SSRC with a real target frequency. `radio_status.c`'s dispatcher
   creates the channel (`create_chan()`), applies the command, and
   sends an immediate synchronous reply (`radio_status.c` lines ~87–99,
   the "channel doesn't yet exist" branch) — but on our client's
   `ensure_channel()` path this initial creation lands the channel at
   `freq=0`, not the requested frequency (start_demod always logs
   `freq 0.000` here regardless of what was requested — a separate
   question about whether that's expected client behavior, flagging it
   since it's part of what we observed, not something we've traced
   further into the client library itself).
2. A second command (the one that would set the real frequency) is
   sent. Since the channel now exists, `radio_status.c`'s "existing
   channel" branch just queues it (`chan->status.command = cmd`, lines
   ~65–80) — no reply is sent from this function at all.
3. `downconvert()` (`radio.c` line 1349) checks
   `if(chan->tune.freq == 0 && chan->lifetime > 0){ if(--chan->lifetime <= 0){ ...return -1; } }`
   **before** reaching the command-processing block (line 1365) that
   would apply and reply to the queued command. On hardware whose
   tunable floor is above 0 Hz (our RTL-SDR: `[R82XX] PLL not locked!`
   at `freq=0`, falls back internally to ~28.8 MHz), this channel's own
   sample/block delivery while parked at an untunable frequency appears
   irregular enough that the queued command sits unprocessed long
   enough to lose the lifetime race in practice (confirmed via `-v -v`
   logging: `dynamically started ssrc ...` appears once, at creation;
   no further log line for that SSRC ever appears, and the client's
   `tune()` call — with a 5s and separately a 15s timeout — times out
   both times, reproduced identically 8+ times across a session).

### Scenario B — an already-alive, already-tuned channel accepts exactly one further command

To rule out anything specific to the freq=0/dynamic-creation path, we
gave a config-declared channel a real starting frequency (in-range for
the hardware) instead of `freq = 0`, so it boots as a normal,
continuously-running channel rather than a dormant prototype.

1. Fresh `radiod` restart. Channel boots and starts producing real
   samples immediately, confirmed via journal and the `control` TUI's
   Signal panel showing real (non-`-inf`/`nan`) values.
2. First `tune()` call to change frequency: succeeds in ~0.05–0.09s,
   full status reply returned, confirmed server-side in the log
   (`command loadpreset(ssrc=...) mode=...`, `set ssrc ... freq = ...`,
   `new filter for chan ...`). The `new filter for chan ...` line
   appearing here — on an ordinary frequency change, not a
   demod-type change — is what suggests `restart_needed` is being set
   for routine retuning, not just mode switches.
3. A second `tune()` call, same channel, same shape, tried at 0s
   (immediately), 5s, and 25s after the first: **every time**, no
   reply, 5.0s client timeout, and the *server* log shows **zero**
   activity for the attempt — not even the periodic per-block noise
   that a healthy channel otherwise produces. The channel does not
   recover with time; only `systemctl restart radiod@<instance>`
   clears it.
4. Separately reproduced via the bundled `control` TUI (not just the
   Python client): a mode change (`nfm`→`am`, a genuine demod-type
   change) on an already-healthy channel produces the identical
   symptom — no reply, no server-side log activity for the attempt.

## Root cause (as far as we traced it)

- `radio_status.c`'s command dispatcher only sends an immediate,
  guaranteed reply when *creating* a channel (`create_chan()` branch).
  For an already-existing channel, a command is only ever **queued**
  (`chan->status.command = cmd`) for the channel's own per-block loop
  to pick up later — and if a command is already queued and
  unprocessed when another arrives, the new one is silently dropped
  (`radio_status.c` line 77, `// An entry already exists. Drop ours,
  until we make this a queue`) — no log, no reply, no error either way.
- The queue is drained in `radio.c`'s `downconvert()` (line 1365),
  which sends the reply. But `demod_thread()` (`radio.c`, the
  `while(status == 0){ switch(chan->demod_type){ ... status =
  demod_fm(p); ... } }` loop) fully **re-enters** the demod function
  from scratch whenever it returns non-zero for a non-fatal reason —
  and `demod_fm()`/`demod_linear()`/`demod_wfm()`/`demod_spectrum()`
  (`fm.c` line 32, `linear.c` line 45, `wfm.c` line 39, `spectrum.c`
  lines 34 and 202) **unconditionally free `chan->status.command` as
  one of their first actions on every entry** — including a restart
  re-entry, not just the channel's initial creation.
- Put together: any command that arrives and gets queued while the
  channel's demod thread is between invocations — mid-restart,
  recreating filters/oscillators/squelch state from scratch — is
  destroyed by that unconditional `FREE()` before it is ever processed
  or replied to. Since ordinary frequency changes appear to trigger a
  restart (`restart_needed`) just as demod-type changes do, this isn't
  limited to mode switches; it makes any *second* live command to an
  existing channel a race against a window we couldn't measure the
  bounds of (didn't recover even after 30s in our testing).

## Question for maintainers

Is this working as designed — i.e., is a `radiod` client expected to
retry a command indefinitely/with its own backoff until it happens to
land outside a restart window, rather than radiod queuing or
acknowledging it reliably? If so, we couldn't find that documented
anywhere we looked, and a single-entry, drop-silently queue combined
with an unbounded (or at least >30s) restart window makes that
extremely difficult for a remote control client with a synchronous
reply-wait model (our case: `ka9q-python`'s `tune()`, but this would
affect any client following the same request/reply pattern). If it's
not intended, the two places that stood out as candidates for a fix:

1. `demod_fm()` et al. freeing `chan->status.command` unconditionally
   on every entry, including restart re-entries — could this check
   whether a command was queued *during* the restart and process it
   once the new demod instance is ready, instead of discarding it?
2. `radio_status.c`'s single-entry "drop ours if one exists" queue —
   even a depth-2 queue, or replacing the newer command instead of
   dropping it, would change a silent, permanent-until-restart failure
   into (at worst) a stale command applied late.

Happy to provide the full `-v -v` logs, packet captures, and exact
`ka9q-python` call sequences for any of the above if useful — this
writeup already reflects a full multi-hour investigation with source
verification at each step, not a first impression.
