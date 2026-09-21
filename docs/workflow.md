# Generic SIGINT Sensing & Correlation Workflow

## Scope

This is a **deployment-agnostic methodology** for building a SIGINT-style sensing
system: a shared RF frontend feeding multiple SDRs/decoders across different
signal domains, normalized into a common event stream, correlated, and exposed
through an AI tool-calling tier. Property-perimeter trespasser detection (the
running example in earlier discussion) is **one instantiation of this pattern**,
not the pattern itself — the same architecture applies to event security, mobile
collection, spectrum monitoring, or any scenario where you're fusing multiple RF
protocol observations into a single operating picture.

The concrete SIGedge/SIGliere property-surveillance spec produced earlier is a
worked example of applying this workflow, kept separately.

## 1. Grounding in published tradecraft

This workflow adapts unclassified, publicly documented frameworks rather than
inventing new ones:

- **PCPAD intelligence cycle** (Planning/Direction → Collection → Processing →
  Exploitation/Analysis → Dissemination) as the top-level loop.
- **EOB (Electronic Order of Battle)** concept — maintain a running inventory of
  known emitters/identifiers; anything not on it is a candidate for analysis.
  Generalizes to any "known identifier library."
- **PDW (Pulse Descriptor Word)** concept from EW literature — one atomic,
  protocol-agnostic record shape (frequency, bandwidth, time, amplitude,
  modulation, identifier) so heterogeneous sensors can be correlated without
  bespoke per-protocol logic.
- **NIST SP 800-61-style severity tiering** — likelihood × confidence × impact
  as the basis for an alert tier, rather than a single binary alarm.
- **BLUF (Bottom Line Up Front)** reporting convention for any human-facing
  summary/report the system produces.

## 2. Generic architecture

```
[RF Frontend] -> [Domain-specific SDR/decoder legs] -> [Normalization bridges]
   -> [Common event bus] -> [Event store] -> [Correlation/tiering engine]
   -> [AI tool-calling tier] -> [External action boundary]
```

### 2.1 RF frontend layer

One or more antennas feed one or more SDRs. If a single antenna serves multiple
SDRs via a splitter (as opposed to physically distributed sensors), this
collapses to a **single collection site** — no bearing/position data is possible,
only presence/absence within range. Distributed multi-site deployments enable
TDOA/multilateration; single-site deployments do not. This is a deployment-time
decision, not something the workflow presumes either way.

Reusable RF budget checklist regardless of deployment specifics:
- Does one antenna need to span the full frequency range of every target domain?
  If so, expect uneven sensitivity at the extremes — budget for a genuinely
  broadband element or accept a coverage tradeoff.
- Splitter/combiner insertion loss compounds with each additional leg — consider
  an LNA before the split point rather than compensating per-leg afterward.
- Cable run loss is frequency-dependent — low-loss cable or shorter runs matter
  more as target frequency increases.
- Confirm real-world coverage (terrain, structures) against theoretical range
  before treating nominal antenna height/gain as ground truth.

### 2.2 Domain-specific bridges → common event schema

Every sensor/decoder, regardless of protocol, normalizes its output into one
PDW-style record:

```json
{
  "event_id": "uuid",
  "ts": "ISO-8601 timestamp",
  "sensor_id": "collection site or node identifier",
  "source": "the decoder/tool that produced this record",
  "domain": "protocol family, e.g. cellular|wifi|bluetooth|aprs|lora|pocsag|...",
  "protocol": "specific protocol/mode",
  "freq_hz": 0,
  "bandwidth_hz": 0,
  "rssi_dbm": 0,
  "modulation": "string",
  "identifier": { "type": "string", "value": "string|null" },
  "geo": {
    "sensor_lat": 0.0, "sensor_lon": 0.0,
    "bearing_deg": null, "target_lat": null, "target_lon": null
  },
  "confidence": 0.0,
  "novelty": "known|unknown|null",
  "tier": "low|medium|high",
  "raw_ref": "pointer back to raw decoder output for audit"
}
```

Design rules that generalize across deployments:
- `identifier.value` is `null` when nothing is decodable — energy-only detection
  is still a valid record.
- `novelty` and `tier` are set by the correlation engine, never by the bridge
  that emits the raw event — bridges only observe, they don't judge.
- `geo.bearing_deg`/`target_lat/lon` are only populated if the deployment
  actually has multi-site geolocation capability; don't fabricate precision a
  single-site deployment doesn't have.
- Add new `domain`/`protocol` values as needed; don't redesign the schema shape
  per protocol.

### 2.3 Transport

Bridges publish normalized records to a common bus (multicast, MQTT, or any
pub/sub mechanism already idiomatic to the platform you're building on) so the
correlation tier subscribes once instead of polling every source individually.
The specific transport technology is an implementation choice, not part of the
methodology — pick whatever fits the existing platform's conventions.

### 2.4 Event store

Persist normalized records somewhere queryable (SQL/SQLite is sufficient at
modest event rates). Append-only log formats (JSONL, etc.) work for a bootstrap/
stub stage but should graduate to a queryable store once anything needs
random-access queries ("what fired in the last hour") rather than a linear tail.

### 2.5 Correlation/tiering engine

A deterministic (non-LLM) process that:
- Resolves `novelty` per identifier by checking known-identifier libraries where
  they exist. **Identifier stability varies by protocol** — some identifiers are
  stable by design (radio callsigns, device addresses assigned at provisioning),
  others rotate/randomize by default (consumer device Bluetooth/WiFi MACs). Only
  treat "unknown" as strong evidence of an unrecognized entity for stable
  identifier types; for unstable ones, use volume/pattern as the signal instead
  of identity matching.
- Computes `tier` from correlation strength: single-domain single hit = low,
  single-domain repeated = medium, multi-domain temporal (and, if the deployment
  has multi-site geolocation, spatial) co-occurrence = high. Tune these
  thresholds empirically during a shakedown period (§4) rather than guessing
  once and trusting it.

### 2.6 AI tool-calling tier

Expose the event store to an LLM via **read-only** tool functions:
`get_recent_events(filters...)`, `correlate_events(...)`, `lookup_known_identifier(...)`.
This lets an operator ask natural-language questions ("what happened near sensor
X last night") instead of writing queries by hand. Keep this tier strictly
read-only — see §3.

### 2.7 External action boundary

**The event store (or a specific tier threshold within it) is the integration
boundary, not a component you build.** Whatever consumes high-tier events to
produce a real-world notification or trigger a real-world response is a separate
concern from the sensing/correlation system, and should stay separate:

- The sensing/AI tier's job ends at making tiered, correlated data reliably
  available.
- Notification mechanism and kinetic/physical response are deployment-specific
  policy decisions made by whoever operates the system, not architecture
  decisions baked into the sensing platform.
- This keeps the AI tier decision-support only — it never becomes the thing
  that triggers a real-world action, which is a deliberate safety property, not
  an accident of scope-cutting.

## 3. Design principle: keep the AI tier read-only

Every tool function exposed to the LLM should be a query, never a side-effecting
action (sending a message, writing to an external system, triggering hardware).
Reasons this generalizes beyond any one deployment:
- Deterministic trigger conditions (a tier threshold) are simpler and more
  auditable as plain code than as something an LLM decides to invoke.
- It bounds what a prompt-injection-style failure or model error can actually do
  — at worst it answers a question wrong, not sends a real notification or takes
  a real action.
- Any action a deployment needs (notification, response) belongs in a separate,
  deterministic watcher process outside the AI tier's tool surface.

## 4. Operational SOP pattern

Regardless of deployment, plan for:

1. **Shakedown period** — run the system reviewing *everything*, including
   low-tier noise, before trusting tier thresholds as the only thing worth
   looking at. Use this to calibrate correlation time windows and thresholds.
2. **Known-identifier library maintenance** — a recurring (e.g. weekly) review
   of recurring "unknown" hits to decide enroll-as-known vs. leave-flagged. This
   is the human feedback loop that keeps the EOB-style baseline current.
3. **Review cadence for sub-threshold tiers** — decide whether low/medium tier
   events get periodic review or are purely forensic (looked at only after an
   incident). Don't leave this undecided by default — undecided defaults to
   "never reviewed."
4. **Reporting convention** — any human-facing summary uses BLUF: lead with
   tier counts and notable correlated events, details after.
5. **Retention/audit** — keep raw records; don't silently discard collection
   history even if summaries are what get reviewed day-to-day.
6. **OPSEC on the system itself** — the existence and capability of a sensing
   system is itself information worth protecting, independent of the deployment
   context.

## 5. Adaptation checklist for a specific deployment

When instantiating this workflow for an actual system, resolve:

- [ ] Single-site or multi-site collection? (Determines whether geolocation is
      possible at all.)
- [ ] Which signal domains are in scope, and what decoder/bridge exists (or
      needs to be built) for each?
- [ ] What identifier types are stable vs. ephemeral for each domain in scope,
      and what does that imply for novelty-scoring confidence?
- [ ] What legal boundaries apply to each domain in this jurisdiction? (e.g.
      passive energy/metadata detection vs. content decode — the line varies
      by protocol and by legal regime; verify per deployment rather than
      assuming a prior deployment's answer transfers.)
- [ ] What existing platform/stack is this being built on top of, and what
      transport/storage conventions does it already have that this workflow
      should reuse rather than duplicate?
- [ ] What triggers the external action boundary (which tier, what conditions),
      and who/what owns building that separate consumer?
- [ ] What's the review/maintenance cadence, and who owns it?

## 6. Worked example (reference only)

A property-perimeter trespasser-detection instantiation of this workflow —
single 30 ft mast, splitter-fed SDRs for cellular presence/Bluetooth/LoRa/APRS,
Ollama+Open WebUI as the AI tier — was worked through in detail as a concrete
example. See the separate SIGedge/SIGliere implementation spec for that specific
instantiation; treat it as an illustration of applying this workflow, not as
part of the workflow itself.
