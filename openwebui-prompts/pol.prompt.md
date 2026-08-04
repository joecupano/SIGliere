# /pol — Pattern-of-Life Reconstruction Prompt

**Purpose.** A saved Prompt (Workspace → Prompts) that reconstructs the
pattern of life for a specific frequency over a specified time window.
Invoked with `/pol <frequency> <days>` in chat, or via the Prompt
picker.

**Command.** `/pol` (case-insensitive; Open WebUI generally normalizes).

**Variables.** Two positional inputs:
- `frequency` — the frequency to profile, MHz or with unit (e.g.
  `146.520`, `144.390 MHz`, `7040 kHz`)
- `days` — the lookback window in days (e.g. `7`, `30`)

**Requires.** The `SIGINT-analyst` custom model (or another model with
the occupancy tool enabled). Prompts are model-agnostic — they run
against whichever model the operator has selected — but the tool call
inside the prompt won't fire unless the model has
`sigint_occupancy_tool` enabled.

**How to install.** See `openwebui-prompts/README.md` for step-by-step
navigation. In short: Workspace → Prompts → + New Prompt → Title
"Pattern of Life", Command `pol`, and paste the block below into the
Prompt Content field. Save.

**Customization.** The timezone in the output-format instructions
defaults to `America/New_York`. Swap for your IANA timezone if you're
not on Eastern.

---

## COPY THIS BLOCK — PASTE INTO PROMPT CONTENT FIELD

```
Reconstruct the pattern of life for {{frequency}} over the last
{{days}} days.

Procedure:

1. Convert {{frequency}} to Hz. If the operator gave MHz, multiply by
   1_000_000. If kHz, multiply by 1_000. Report the Hz value you're
   about to query.

2. Call query_occupancy with:
   - low_hz  = <frequency_hz> - 5000    (±5 kHz tolerance)
   - high_hz = <frequency_hz> + 5000
   - mode    = null                     (any mode)
   - lookback_seconds = {{days}} * 86400

3. If zero sightings come back, stop and report: "No sightings on
   <frequency> in the last {{days}} days. This may mean the frequency
   is quiet, the producer covering that band was not running, or the
   frequency is outside the demodulated channels radiod publishes on
   this build." Then list the closest active frequencies from a
   broader lookup so the operator can spot-check whether the
   frequency-tolerance was too narrow.

4. If sightings came back, group them:
   - By hour of day, converted from UTC to America/New_York local
   - By day of week (Mon-Sun local)
   - By calendar date (to catch days with no activity)

5. Report findings in this order:

   a) One-sentence summary: total sighting count over the window,
      and whether activity is concentrated, distributed, or sparse.

   b) A bulleted schedule table showing hour × day-of-week activity
      level. Use these bands: 0 sightings blank, 1-5 low, 6-20 med,
      21+ high. Include the header row with days of week and the
      column of hours 00-23.

   c) A list of the most-active hour(s) of day and most-active day(s)
      of week, with exact counts.

   d) Any calendar dates with zero sightings. Flag them explicitly as
      "possible producer downtime, not necessarily radio silence" —
      the operator will know which of the {{days}} days the box was
      actually up.

   e) Any single-sighting outliers — timestamps when the frequency
      fired exactly once and had no neighbors within an hour. These
      are often more interesting than routine traffic (a stray keyup,
      a test transmission, a signal that wasn't the intended
      inhabitant of the channel).

6. Do not speculate about who is transmitting or what they're doing.
   Report only what the sightings show. If the operator wants
   interpretation, they'll ask a follow-up.

7. If the sighting counts across the whole window are unusually low
   given the frequency's typical use (e.g. a calling frequency like
   146.520 with fewer than 10 sightings across 7 days), note that as
   a pattern-of-life datapoint in its own right — "quiet" is a
   pattern too.
```

---

## Example invocations

**Weekend repeater usage on 146.760:**
```
/pol 146.760 14
```
Two-week window. Look for evening / weekend commuter patterns, morning
nets, etc.

**APRS activity on the national channel:**
```
/pol 144.390 30
```
Thirty-day view of APRS activity — should look continuously active with
some diurnal variation.

**A specific HF frequency you're curious about:**
```
/pol 7040 7
```
Seven-day view of the 40 m QRP watering hole. Should show evening peaks
if the band is opening.

## Notes on the prompt design

The `±5 kHz tolerance` in step 2 is calibrated for HF channelization
where radiod's demodulated channels are typically 3-5 kHz wide. For
VHF/UHF FM channels (12.5 or 25 kHz), the operator may want a wider
tolerance — but the current occupancy DB stores per-channel bins
matching what the producer sweeps, so ±5 kHz almost always centers
correctly. If you find pattern-of-life queries returning empty when you
know activity exists, try widening to ±25000 by editing this prompt.

Step 3's "closest active frequencies" fallback exists because the most
common cause of an empty pattern-of-life result is asking about a
frequency that's not in radiod's channel list. Rather than reporting
"nothing," the LLM points the operator at what IS active nearby so they
can adjust.

Step 5(d)'s "flag zero-sighting days as possible downtime" is the
honest counterpart to the query. Producers do occasionally stop
(reboots, USB re-enumeration, manual mode switches). Without this
clause, a day with a stopped producer looks identical in the output to
a day of genuine radio silence. With it, the operator gets to
reconcile against their own memory of what the box was doing.

Step 6's "no speculation" clause is the same principle as the
SIGINT-analyst system prompt's overall posture — reporting from data,
not synthesizing narratives. Pattern-of-life data by itself doesn't
tell you WHO is transmitting; it tells you WHEN activity happens. Any
who-is-it inference is a follow-up conversation the operator initiates.
