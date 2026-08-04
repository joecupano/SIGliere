# openwebui-prompts

Open WebUI configurations for sovereign SIGINT operations — Custom
Models (system-prompt-scoped baselines) and saved Prompts (invocable
templates). This directory is the source of truth for prompts that live
inside Open WebUI's own database; **the repo is where they're versioned
and portable**, the container is where they're active.

## What's here

| File | Type | Purpose |
|---|---|---|
| `SIGINT-analyst.system-prompt.md` | Custom Model system prompt | Standing analytical posture for every SIGINT chat — tool-first, quote-exact, never speculate |
| `pol.prompt.md` | Saved Prompt template | `/pol <frequency> <days>` — reconstruct pattern of life for a specific frequency over a window |

Each file has front matter explaining what it does, a "COPY THIS BLOCK"
section with the exact text to paste into Open WebUI, and notes on the
design choices behind individual clauses.

## Why this lives in the repo (not just in Open WebUI)

Open WebUI stores Custom Models and Prompts in its own SQLite database
inside the container's writable state volume (`open-webui-state` on
this build). Two consequences worth naming:

- **They survive normal container restarts** — Podman restart, host
  reboot, `podman pull` for a version bump. The state volume is
  persistent.
- **They do NOT survive a state-volume reset.** If you ever have to
  wipe the state (recover from a corrupted DB, do a fresh install on
  a new box, restore to a different rubberduck), the Custom Models
  and Prompts are gone. Open WebUI has a JSON export/import in the
  Admin panel, but relying on that alone is fragile — if the state
  is corrupted, the export path may not work either.

Keeping the source of truth here in git means: at any moment you can
open the two `.md` files, copy the blocks, paste them into a fresh
Open WebUI, and the analytical posture is restored. That decoupling —
"the repo remembers what the container should look like" — is the
same pattern the phase scripts follow for services and mounts.

## How to install `SIGINT-analyst` (Custom Model)

**Open WebUI 0.11.x note:** the UI layout is a little different from 0.10.x,
but the targets are the same. Use **Workspace** for per-workspace models,
tools, and prompts, and use **Admin Panel → Settings → Connections / Models**
for Ollama connectivity and model pulls. In 0.11.x the add action may be
labeled **+ New Model**, **Add Model**, or appear as a **+** in the empty pane.

**Prerequisite:** all four native tools already imported and enabled
in Open WebUI. If not, install them first from `openwebui-tools/` per
the README there. Verify at Workspace → Tools that you see:

- `sigint_occupancy_tool`
- `sigint_kismet_tool`
- `sigid_reference_tool`
- `sigint_whisper_tool`

**Then install the model:**

1. Open Open WebUI in a browser (`http://localhost:8080` locally, or
   via Caddy at your LAN URL).
2. Navigate to **Workspace → Models**.
3. Click the add/create action in the Models pane (in 0.11.x this is often
   **+ New Model** or **Add Model**; if the pane is empty, look for the
   **+** button or the "Create" action in the header).
4. Fill in:
   - **Name:** `SIGINT-analyst`
   - **Base Model:** `qwen3:14b` (or `llama3-groq-tool-use:8b` for the
     faster / lower-VRAM option; the system prompt works with either)
   - If **Workspace → Models** shows `0`, that is not a failure: in 0.11.x
     this screen is the workspace model registry. Create a new entry here and
     select one of the Ollama models you already pulled (for example
     `qwen3:14b`) as the base model.
   - **System Prompt:** open `SIGINT-analyst.system-prompt.md` in this
     directory, find the section headed "COPY THIS BLOCK — PASTE INTO
     SYSTEM PROMPT FIELD", and paste the contents of the fenced code
     block below that heading. Before saving, replace the three
     placeholders:
     - `<CALLSIGN>` — your amateur radio callsign
     - `<LOCATION>` — your grid + city (e.g. `FN21wg, Mountainville, NY`)
     - `<TIMEZONE>` — your IANA timezone (e.g. `America/New_York`)
5. Under **Tools** (or "Capabilities" — the section that lists
   enable-able tools per model), tick each of the four native tools
   listed above.
6. **Save.**

You now have `SIGINT-analyst` selectable in the model picker at the
top of any chat window.

## How to install `/pol` (Saved Prompt)

1. Navigate to **Workspace → Prompts**.
2. Click the add/create action for prompts (in 0.11.x this is often
   **+ New Prompt** or **Add Prompt**; the exact label varies by build).
3. Fill in:
   - **Title:** `Pattern of Life`
   - **Command:** `pol` (Open WebUI adds the `/` prefix automatically
     in chat; do not include it here)
   - **Prompt Content:** open `pol.prompt.md` in this directory, find
     the "COPY THIS BLOCK — PASTE INTO PROMPT CONTENT FIELD" section,
     and paste the contents of the fenced block below that heading.
     The `{{frequency}}` and `{{days}}` placeholders are Open WebUI's
     own variable syntax — leave them exactly as written. Optionally
     replace the timezone (`America/New_York`) if you're not on
     Eastern.
4. **Save.**

The prompt is now available in any chat window. Trigger it by typing
`/pol` — Open WebUI will pop up a small form asking for `frequency`
and `days`, then substitute your inputs into the template and send to
the model.

## How to use them together

The typical operator workflow:

1. Open a new chat.
2. Select the **`SIGINT-analyst`** model from the picker at the top.
3. Ask questions normally — the standing posture applies to every
   turn, so tool-first answering is automatic. Example:
   > What's been active on 20 meters in the last 8 hours?
4. When you want a structured pattern-of-life view of a specific
   frequency, type `/pol` — the form pops up, fill in `frequency`
   (e.g. `146.520`) and `days` (e.g. `7`), submit. The full
   pattern-of-life prompt goes to the model, which runs the
   occupancy tool with the correct window and returns a structured
   analysis.

The two work together: the custom model gives you a persistent
"always tool-first, never speculate" baseline; the saved prompt gives
you a structured procedure for a specific analytical task without
having to re-type the whole thing every time.

## Version control / backup workflow

Since Open WebUI holds the live configuration in its own database,
this directory is the human-readable-and-editable source. Two
practices worth adopting:

**When you edit a prompt in the Open WebUI UI:** if the edit is worth
keeping, mirror it back to the corresponding `.md` file in this
directory and commit. That way the repo stays in sync with what's
actually running.

**When you rebuild or restore Open WebUI:** re-apply from these files,
not from an old export.json. Manual paste is more effort but produces
a definitively-working configuration and forces you to notice if
Open WebUI's schema has changed between versions.

If you want the option-B mechanical path anyway: Open WebUI's admin
panel has a "Prompts" export that produces JSON, and the same for
Models. Storing those JSON exports alongside the `.md` files is
fine — but the `.md` files are the authoritative human-readable
version.

## Caveats and known behavior

**Open WebUI version compatibility.** These prompts were designed and
tested against Open WebUI v0.10.x and forward-compatible with v0.11.0
(the redesigned-UI release). If a future version changes the tool
schema format or the prompt-variable syntax, the affected file will
need an update. Both files pin their dependencies (which model, which
tool names, which variable-substitution syntax) in the front matter
for exactly this reason.

**Model-specific behavior.** `qwen3:14b` follows the standing posture
more faithfully than `llama3-groq-tool-use:8b` — expect the smaller
model to occasionally add speculation despite clause 1, and to
paraphrase counts despite clause 3. If you need strict adherence for
report-writing use cases, stick with `qwen3:14b`.

**The `/pol` prompt is single-frequency.** For multi-frequency or
band-sweep analyses, don't try to stretch this prompt — write a new
one. Prompts are cheap to add; overloading one prompt with multiple
modes makes it fragile.

**No secrets in prompts.** Because prompts are visible to the LLM at
every turn, do not put API keys, private URLs, or other secrets into
either file. The callsign / location / timezone are the only per-site
values, and they're public record (callsign) or approximate (grid to
6 digits). Anything more specific belongs in User Variables (post-
0.11.0) or in a Knowledge collection scoped to the model, not in the
system prompt.

## Adding more prompts later

The convention this directory establishes:

- One `.md` file per prompt / model
- Named `<name>.prompt.md` for saved prompts, `<name>.system-prompt.md`
  for model system prompts
- Each file has front matter explaining purpose, install target,
  variables, prerequisites
- Each file has a clearly-marked "COPY THIS BLOCK" section with the
  exact paste-ready text
- Each file has notes on design choices for individual clauses so
  future edits are informed

When you build the next few — a `/wifi-delta` saved prompt for new-
device detection, a `/correlate` saved prompt for cross-source
synthesis, a `SIGINT-triage` custom model for scan-oriented terse
output — follow the same convention and the directory scales
cleanly.

## Related documentation

- `openwebui-tools/` — the four native tools these prompts invoke
- `docs/openwebui-setup-guide.md` — installing Open WebUI itself
- `docs/build-order.md` Phase 4 — the platform-level Open WebUI
  install
