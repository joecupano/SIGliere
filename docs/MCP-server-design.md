# MCP Server Design for SIGINT SDR Control and Radiod Access

## Purpose

This document combines the design and security requirements for a host-side MCP server that can expose SDR state and control through the existing radiod-based architecture. The goal is to make SDR availability, tuning, mode selection, and demodulator management available through structured tool calls rather than ad hoc shell commands or manual edits.

This single document supersedes the former split between the design note and the security requirements note. The current working path for local chat remains the native Open WebUI tool approach, but this MCP design captures the intended future control plane for the radio stack.

The design is intended for the current build topology:

- RX-888 via radiod for HF and wideband monitoring
- HackRF via radiod for VHF/UHF channels
- ~~RTL-SDR via ad hoc or scripted tasking~~ — **tried and descoped**
  (2026-08-06): the client/MCP side was built and fixed, but a
  `ka9q-radio` bug limits a live-tasked channel to one control command
  per `radiod` restart — see
  [ka9q-radio-upstream-issue-command-queue.md](ka9q-radio-upstream-issue-command-queue.md)
  and [mcp-validation-evidence.md](mcp-validation-evidence.md). RTL-SDR
  is OpenWebRX+-only until/unless that's patched upstream.

## Goals

1. Expose SDR state to chat and automation through a consistent MCP interface.
2. Allow safe frequency and mode changes through radiod-managed paths.
3. Provide a single control surface for:
   - current SDR availability,
   - current tuning state,
   - supported modes,
   - demodulator attachment and detachment,
   - configuration selection and reload.
4. Preserve the existing single-owner SDR model and avoid device conflicts.

## Non-Goals

- Direct raw device access outside the radiod control layer.
- Arbitrary shell execution from the model.
- Allowing the AI to bypass ownership arbitration or security controls.
- Implementing a full packet decoder or DSP pipeline inside the MCP server.

## Design Principles

### 1. Radiod is the control boundary

The MCP server should not talk to SDR hardware directly. It should drive the same control path used by the build:

- radiod configuration files in [ingest/ka9q-radio](../ingest/ka9q-radio)
- service ownership logic in [scripts/sdr-mode.sh](../scripts/sdr-mode.sh)
- runtime status and state from radiod and the host system

This keeps the server aligned with the existing architecture and avoids duplicated control logic.

### 2. Single-owner enforcement is mandatory

Each SDR can only be owned by one active consumer at a time. The MCP server must never bypass that rule. Instead, it should:

- inspect current ownership state,
- request or release ownership through the supported control mechanism,
- refuse unsafe actions when the SDR is unavailable.

### 3. Tool actions must be narrow and validated

Every MCP tool should enforce explicit allowlists and ranges. For example:

- frequency must be within a known supported range for that SDR class,
- mode must be one of the configured allowable modes,
- demodulator names must come from a known registry,
- configuration names must be known deployment profiles.

### 4. Read-only tools come first

The first version should expose read-only tools for:

- current SDR availability,
- current radiod state,
- active configuration profiles,
- current frequency/mode assignments,
- available demodulator instances.

Action tools can be added later once the control path is proven safe.

## Threat Model

The MCP server would be a host-side control plane, so it must assume the following risks:

1. Injection via model-supplied arguments.
2. Prompt-injection chaining into tool calls.
3. Unauthenticated network access to the tool surface.
4. Over-broad tool capability.
5. Resource exhaustion and device contention.
6. Excessive privilege of the server process itself.

## Security Requirements

The server should follow the same hardening pattern described below:

### R1 — Read-only first; actions are separate, later, individual decisions
The initial server exposes only read/query tools. Any tool with side effects is added later, one at a time, under its own review.

### R2 — Narrow, single-purpose tools with validated parameters
Each tool does one well-defined thing. Parameters are constrained to allowlists and numeric ranges, and no free-form SQL, shell, or path parameters are accepted.

### R3 — Parameterized queries, always
All database access uses parameter placeholders rather than string-formatted SQL.

### R4 — No shell string interpolation
Any subprocess execution uses an argument list, never shell interpolation.

### R5 — Path confinement
Any path-like parameter must be sanitized and confined to an allowlisted base directory.

### R6 — Loopback bind + firewall
The MCP server binds to loopback only and is protected by firewall policy so it is not exposed to the LAN.

### R7 — Least-privilege service account
The server runs as a dedicated service account with only the read access it needs.

### R8 — Authentication for side-effecting tools
Any action tool must require an authentication mechanism or other explicit protection.

### R9 — Rate limiting and device arbitration for action tools
Action tools must respect single-owner SDR arbitration and be rate-limited.

### R10 — Treat untrusted decoded content as hostile input
Even if the model sees decoded content, tools must not act on it without independent validation.

## Proposed Architecture

### Components

1. MCP Server Process
   - Hosts the MCP endpoint.
   - Exposes tools for status and control.
   - Runs as a dedicated service account with limited privileges.

2. SDR State Manager
   - Maintains the current understood state of each SDR.
   - Reads from radiod status, config files, and host service state.
   - Provides a normalized model for the MCP tools.

3. Radiod Adapter
   - Encapsulates interactions with radiod.
   - Knows how to:
     - read status,
     - validate a config/profile,
     - request a configuration reload,
     - task a frequency/mode change where supported.

4. Ownership/Arbitration Layer
   - Prevents conflicting use of an SDR.
   - Enforces the same ownership model as [scripts/sdr-mode.sh](../scripts/sdr-mode.sh).
   - Rejects change requests when the SDR is in use by another consumer.

5. Configuration Registry
   - A declarative list of supported SDR profiles and their ranges.
   - Example entries:
     - RX-888: HF / wideband profiles
     - HackRF: 2m / 70cm profiles
     - RTL-SDR: ad hoc or single-frequency presets

## Suggested MCP Tools

### Read-Only Tools

- `list_sdrs`
  - Returns all known SDRs and their current state.

- `get_sdr_status`
  - Returns availability, owner, configured profile, current frequency, current mode, and active demodulators.

- `list_profiles`
  - Lists the available radiod config profiles for an SDR.

- `list_demodulators`
  - Lists currently attached or candidate demodulators for an SDR.

- `get_radiod_health`
  - Returns whether radiod is active, healthy, and serving expected streams.

### Action Tools

- `set_profile`
  - Switch an SDR to a known profile.

- `set_frequency`
  - Change the current tuned frequency if the selected profile and radiod implementation allow it.

- `set_mode`
  - Change demodulation mode for an active channel, such as `fm`, `usb`, `lsb`, `am`, or `cw`.

- `attach_demodulator`
  - Connect a known demodulator/channel to the current SDR configuration.

- `detach_demodulator`
  - Remove a demodulator/channel from the active configuration.

- `reload_configuration`
  - Reload the radiod configuration for the selected SDR after a profile or channel change.

## Data Model

A normalized SDR state object should include:

```json
{
  "sdr_id": "hackrf-1",
  "kind": "hackrf",
  "available": true,
  "owner": "radiod",
  "profile": "hackrf-2m",
  "frequency_hz": 144390000,
  "mode": "fm",
  "demodulators": ["aprs", "voice"],
  "last_error": null
}
```

## Configuration Registry Example

The registry should live as a structured file or embedded module so the tools can validate requests without parsing arbitrary user input.

Example structure:

```yaml
sdrs:
  rx888:
    kind: rx888
    profiles:
      - hf-default
    frequency_range_hz: [1000000, 30000000]
    modes: [usb, lsb, am, cw, fm]
  hackrf:
    kind: hackrf
    profiles:
      - hackrf-2m
      - hackrf-70cm
    frequency_range_hz: [1000000, 600000000]
    modes: [fm, usb, lsb, am, cw]
  rtlsdr:
    kind: rtlsdr
    profiles:
      - adhoc
    frequency_range_hz: [24000000, 1766000000]
    modes: [fm, usb, lsb, am, cw]
```

## Implementation Plan

### Phase 1: Status and discovery

- Implement MCP server skeleton.
- Add read-only tools for list/status/profile/demodulator state.
- Add host-side adapters for radiod and service status inspection.

### Phase 2: Safe control hooks

- Add action tools for profile selection and reload.
- Validate frequency and mode against the config registry.
- Enforce owner and availability checks before each change.

### Phase 3: Demodulator lifecycle

- Add attach/detach operations for named demodulators or channel instances.
- Track the active demodulator set in a small state store.

### Phase 4: Operational hardening

- Add auth or token protection for action tools.
- Add logging and audit trail.
- Add test coverage for validation and ownership refusal cases.

## Deployment Shape

The MCP server should run as a host-local service, not as a containerized component with direct access to the SDR stack unless the container is given explicit host privileges. The preferred deployment is:

- host-side process,
- loopback-only listener,
- integration through the existing radiod and service scripts.

## Open Questions

1. Which radiod control interface is available on the deployed build for live reconfiguration?
2. Should frequency changes be implemented as full profile swaps or as targeted channel re-tasking?
3. Should demodulator attachment be implemented as a generic channel map or as a fixed registry of known decoders?
4. Do we need a separate approval layer for high-impact actions such as changing the active SDR owner?

## Recommendation

Implement the server in two layers:

1. A conservative status/query layer first.
2. A narrow control layer second, gated by ownership checks and validation.

That approach preserves the current build’s safety model while still opening the door to chat-driven SDR configuration through a structured MCP interface.
