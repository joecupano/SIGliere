# SIGINT MCP Server — Security Requirements (design-first)

> **Status (2026-08): design complete and documented on main.** This document
> and [MCP-server-design.md](MCP-server-design.md) define the intended host-side
> MCP architecture for SIGINT tooling in this build. The current working path
> for local chat remains the native Open WebUI tool approach; MCP is a future
> integration path when client compatibility and deployment constraints are
> clear.
>
> **Data note:** the highest-value tool (`query_occupancy`) reads the
> occupancy DB, which is sparse until the radiod occupancy producer is built —
> so reviving the AI integration is most useful *after* that producer exists.

These requirements are satisfied by the MCP server that exposes SIGINT tools
(occupancy queries, signal candidate lookup, radiod status, and later
capture/render actions) to an LLM client such as Open WebUI. Written before
code so the design started constrained rather than retrofitting security
later.

## Why this document exists

Every other service in this build runs rootless in Podman specifically to
contain blast radius. The SIGINT MCP server is the deliberate exception: it
runs **host-side**, because its tools need host resources the container can't
reach — the occupancy database, radiod's multicast/status, the SDR devices,
the GPU, and the processing venvs. That expanded privilege means the
isolation that protects the rest of the stack does **not** protect this
component. The discipline therefore moves from "the container contains it"
into the tool design and configuration. This document is that discipline,
made explicit.

## Threat model (what we are defending against)

1. **Injection via model-supplied arguments.** Tool arguments originate from
   chat prompts. Any tool that builds SQL, a shell command, or a filesystem
   path from those arguments by string concatenation is an injection vector —
   now executing host-side with real privileges.
2. **Prompt-injection → tool-call chaining.** If the AI ingests untrusted
   content (decoded signal text, external documents, web results) containing
   embedded instructions, a manipulated prompt could try to drive the model
   into calling tools with malicious arguments.
3. **Unauthenticated network access to the tool surface.** An MCP server
   listening beyond loopback exposes SIGINT tools — potentially including
   capture/trigger actions — to anything on the LAN, with no auth.
4. **Over-broad tool capability.** A flexible tool (`run_query(sql)`,
   `capture(arbitrary_params)`) hands the model (and thus a prompt) far more
   power than any single legitimate use requires.
5. **Resource exhaustion / device contention.** Tools that trigger captures,
   renders, or GPU work consume real hardware; abuse (a model loop, a
   malicious prompt) can DoS the box or yank the RX-888 from radiod.
6. **Excessive privilege of the server process itself.** Running as the full
   operator account or root gives a compromised tool far more reach than its
   function needs.

## Hard requirements

### R1 — Read-only first; actions are separate, later, individual decisions
The initial server exposes ONLY read/query tools (occupancy queries, signal
ID lookup, radiod status). Read-only tools whose parameters are validated
against known values have a small, acceptable surface: the worst a malicious
call achieves is returning data the operator could already see. Any tool with
side effects (capture, trigger, render, write) is added later, one at a time,
each as its own explicit security review — never as a batch, never as a
convenience.

### R2 — Narrow, single-purpose tools with validated parameters
Each tool does one well-defined thing. Parameters are constrained:
- Enumerations validated against an allowlist (e.g. `band` ∈ a fixed set of
  known bands; `mode` ∈ a fixed set of demod modes).
- Numeric ranges bounds-checked (frequencies, durations, timeframes).
- **No free-form SQL, shell, or path parameters. Ever.** A tool that would
  need arbitrary SQL is a design failure — decompose it into specific,
  parameterized queries instead.
Narrow tools make injection structurally hard rather than relying on
downstream sanitization. This is the single biggest security lever.

### R3 — Parameterized queries, always
All database access uses parameter placeholders (`?`), exactly as
`db/occupancy_db.py` already does throughout (e.g.
`SELECT ... WHERE signal_key = ?`). String-formatted/f-string SQL is
prohibited. This is an existing discipline in the codebase — do not regress
it in the MCP layer.

### R4 — No shell string interpolation
Any tool that executes a subprocess uses an argument list
(`subprocess.run([...])`), never `shell=True` with interpolated arguments.
Model-supplied values are passed as discrete list elements, never spliced
into a command string.

### R5 — Path confinement
Any tool accepting a filename or path sanitizes it (the `re.sub` pattern in
`sigid_mirror.py` is the reference) and confines the result to an explicit
allowlisted base directory. Reject anything resolving outside it (no `..`
traversal, no absolute paths escaping the base).

### R6 — Loopback bind + firewall
The MCP server binds `127.0.0.1` only — never `0.0.0.0`. Open WebUI (and any
other host-local client) reaches it via the host loopback. The port is
covered by ufw's default-deny, consistent with how Ollama's :11434 was
handled. An unauthenticated tool endpoint on the LAN is an exposure; loopback
removes the LAN entirely from the attack surface.

### R7 — Least-privilege service account
The server runs as a dedicated service account (pattern: the `ollama` and
`radio` system users), NOT the operator account and NOT root. The account
gets exactly the access its tools need:
- Read access to the occupancy DB, SigID mirror, radiod status.
- **No write access** unless a specific tool provably requires it (and then
  scoped to only what that tool touches).
- No shell, no login.

### R8 — Authentication for side-effecting tools
Pure read-only tools on loopback are lower stakes. But any tool with side
effects must not be invokable by an arbitrary local process without a token /
credential. Use MCP's auth provisions; do not rely on loopback alone once
actions exist.

### R9 — Rate limiting and device arbitration for action tools
When action tools are eventually added:
- Expensive tools (capture, spectrogram render, GPU work) are rate-limited.
- Capture-type tools MUST respect the single-owner SDR arbitration — they may
  not seize the RX-888 from radiod. They coordinate through the existing
  `rx888-mode.sh` model (or refuse if the device is owned), never bypass it.

### R10 — Treat untrusted decoded content as hostile input
Decoded signal text, OCR output, and any externally-sourced content the AI
might reason over is untrusted. Tools do not act on instructions found inside
such content. Argument validation (R2) is enforced independently of the
model's stated intent, so a prompt-injected tool call still hits the same
allowlist/range checks.

## Design consequences (how these shape the build)

- The first server is a small `fastmcp` server exposing three read-only
  tools: `query_occupancy`, `lookup_signal_candidate`, `radiod_status`.
  (The third is `lookup_signal_candidate` — returning candidate SigIDs
  already recorded for LOGGED signals — rather than a from-scratch
  `identify_signal` classifier, because the SigID mirror is a sync-tracking
  manifest, not a queryable signal-characteristics database; open-ended
  "what signal is this?" stays with the RAG path.) `fastmcp` is the
  recommended framework — already used elsewhere in the operator's work.
- It binds loopback, runs as a dedicated read-only service account, and every
  parameter is enum/range-validated at the tool boundary.
- Open WebUI is one MCP client among potentially several (the same server is
  portable to other MCP clients — a reason to prefer MCP over a bespoke HTTP
  trigger service).
- Action tools (capture/render/trigger) are explicitly OUT OF SCOPE for the
  first server and gated behind their own future review, each satisfying
  R8/R9 before it ships.

## Pre-implementation checklist

Before writing the server:
- [ ] Confirm the Open WebUI version consumes MCP cleanly (native or via a
      documented bridge/pipe). If MCP support is immature, defer or use an
      interim loopback HTTP+native-tool path designed to migrate to MCP.
- [ ] Create the dedicated service account with read-only access to the
      occupancy DB / SigID mirror / radiod status; verify it CANNOT write.
- [ ] Define the parameter allowlists (bands, modes) and numeric ranges up
      front, as data, so tools validate against them.
- [ ] Decide the loopback port and add the ufw rule (default-deny covers it).
- [ ] Confirm no tool in the initial set has any side effect (read-only gate).
