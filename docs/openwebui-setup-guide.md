# Setting Up Open WebUI — The Sovereign AI Front End

Open WebUI is the chat interface for this build's local AI: it talks to the
local Ollama models and hosts the **native tools** that let the model query
your own SIGINT data (occupancy, Kismet, SigID, audio, SDR control). Every
other AI guide in this repo assumes Open WebUI is up and a tool is installed
the way this guide describes. Start here.

This guide targets the exact image this repo pins:
**`ghcr.io/open-webui/open-webui:v0.11.0`** (`containers/open-webui.container`).
Every menu path and label below was checked live against a running `v0.11.0`
instance, not assumed from release notes — if you deliberately move the pin
to a newer tag, treat menu placements here as a starting point to re-verify,
not a guarantee.

## How this guide is organized

Work through the sections in order on a fresh install:

1. **What's actually running** — the architecture, so troubleshooting later
   makes sense.
2. **First boot: create the admin account.**
3. **Connect Ollama and pull the models.**
4. **Orientation** — where things live in the 0.11.0 UI.
5. **Installing a native tool** — the reusable procedure every SIGINT tool
   guide in this repo links back to. If Open WebUI is already running and you
   just need to add or debug a tool, jump straight there.
6. **The tools this build installs** — what each one does and where its own
   guide lives.
7. **Optional: External OpenAPI connection** and **Knowledge (RAG)**.
8. **Troubleshooting** — the gotchas that cost real time building this.

---

## 1. What's actually running

Open WebUI runs as a **rootless Podman container** (a systemd **Quadlet**,
`~/.config/containers/systemd/open-webui.container`), bound to loopback
`127.0.0.1:8080` only. **Caddy** is the actual LAN-facing entry point,
reverse-proxying to that loopback address — Open WebUI itself is never
exposed directly. The container reaches the host's **Ollama** (the model
runtime, native on the host, not containerized) via
`http://host.containers.internal:11434`. Both are systemd `--user` services
and start on boot; you don't manage them by hand per session.

**Default address:** `http://<box-ip>:8000/` (plain HTTP — see
`containers/Caddyfile`; Caddy binds `:8000`, not `:80`, because rootless
Podman can't bind privileged ports without a host-wide policy change). On the
box itself, `http://localhost:8080` also reaches Open WebUI directly,
bypassing Caddy. If you ran Phase 4 with `CADDY_TLS=1`, use `:8443` and
`https://` instead — see `docs/security-hardening.md` § Caddy.

### Step 1.1 — Confirm both services are actually up

```
systemctl --user status open-webui
systemctl --user status caddy
```

Both should show `active (running)`. If either doesn't, `scripts/phase4-open-webui.sh`
(re-run any time — it's idempotent) or `journalctl --user -u open-webui -f` /
`journalctl --user -u caddy -f` for the failure.

---

## 2. First boot: create the admin account

**Why this matters:** the **first** account ever created on a fresh Open
WebUI instance automatically becomes the administrator — there's no separate
"make me admin" step. On a sovereign single-operator box, that's you, and
it's the only account you'll need.

### Steps

1. Browse to the address from §1 (`http://<box-ip>:8000/`). A fresh instance
   shows a **sign-up** screen, not a login screen.
2. Create your account: name, email, password. Because this is local-first,
   there's no cloud account and no external verification — the "email" field
   is just a local identifier, not checked against anything. Any value works.
3. That account now has admin rights, reachable via **Admin Panel** in the
   user menu (top-right avatar).

There is no password-reset-by-email here — it's a local account with no mail
server behind it. Keep the password in your password manager.

---

## 3. Connect Ollama and pull the models

**Why these four models:** this build pulls a deliberately small, role-based
set rather than one general model, because tool-calling reliability and
vision capability turned out to be mutually exclusive in practice (see the
comparison table below).

| Model | Role | Notes |
|---|---|---|
| `qwen3:14b` | general reasoning **and** tool calling | Newer (2025), verbose — explains results and suggests next steps. |
| `llama3-groq-tool-use:8b` | tool calling, alternative | Older (Llama 3, Jul 2024) but purpose-built for reliable function calling. Faster, terser. `TOOL_MODEL=skip` in Phase 3 omits it if you only want `qwen3`. |
| `gemma3:12b` | vision (waterfall/spectrogram images) | **Cannot call tools at all** — a real Ollama limitation, not a misconfiguration. See the vision guide's two-model workflow. |
| `nomic-embed-text` | embeddings, for Knowledge/RAG | ~274MB. |

**Which tool model — `qwen3:14b` or `llama3-groq-tool-use:8b`?** Both were
tested against every SIGINT native tool on a real build and **both fire tools
reliably** once the tool is actually enabled for the conversation (§5, step
E — an earlier apparent Groq failure during development turned out to be a
disabled integration, not the model). The only real difference is style:

| | `llama3-groq-tool-use:8b` | `qwen3:14b` |
|---|---|---|
| Fires all tools | yes | yes |
| Speed | faster | slower |
| Size | 4.7 GB | 9.3 GB |
| Response style | terse, gets to the result | verbose, explains and suggests next steps |

Neither is objectively better — Groq suits fast operational queries, `qwen3`
suits interpretation/teaching. Both ship in this build; pick per preference
when you register a Workspace model in §5 step D. Note `llama3-groq-tool-use`
occasionally needs more explicit phrasing ("use the tool now with no
arguments") where `qwen3` fires on a plain request.

### Steps

**A. Confirm the connection.** **Admin Panel → Settings → Connections**
should list the Ollama endpoint (`http://host.containers.internal:11434`) as
reachable. If it isn't, the container can't see host Ollama — check that
Ollama is actually running on the host (`systemctl status ollama`) and that
the Quadlet's `OLLAMA_BASE_URL` / `--add-host` lines are intact
(`containers/open-webui.container`).

**B. Pull the models.** Simplest from the host shell:

```
ollama pull qwen3:14b
ollama pull llama3-groq-tool-use:8b
ollama pull gemma3:12b
ollama pull nomic-embed-text
```

(Equivalently, from the UI: **Admin Panel → Settings → Models**.)

**C. Understand `Workspace → Models` in 0.11.0.** This pane is a **workspace
model registry**, not an auto-populated list of every Ollama model you've
pulled. Seeing `0` there is expected until you deliberately create a
Workspace model entry for one of the discovered Ollama models — that's §5
step D, and it's where you'll register `qwen3:14b` (or `llama3-groq-tool-use:8b`)
for tool use specifically.

---

## 4. Orientation: where things live in 0.11.0

**Why this matters:** 0.11.0 renamed and relocated a few things relative to
older Open WebUI releases. Getting the two-menu mental model right up front
avoids hunting.

- **Workspace** (left sidebar) → **Models**, **Tools**, **Prompts**,
  **Knowledge**. This is where you register a model for tool use, install
  native tools, add saved prompts, and manage RAG collections. Everything in
  §5 and §6 happens here.
- **Admin Panel** (user-menu avatar, top-right) → **Settings** →
  **Connections / Models / Tools**. Server-wide configuration: the Ollama
  connection (§3A) and bulk model management live here.
- The **chat view** has a model selector at the top and, once a tool is
  enabled for the conversation, an **Integrations** control near the message
  box (§5 step E) — this is the per-chat tool on/off switch.

---

## 5. Installing a native tool

*(This is the reusable procedure the occupancy, Kismet, SigID, whisper, and
operator-control guides all point back to. It captures what broke during
real setup — follow it in order and tools fire; skip a step and they
silently won't.)*

**Why native, not external OpenAPI/MCP:** a "native tool" is one of this
repo's Python files in `openwebui-tools/` that runs **in-process inside the
Open WebUI container** and reads your data directly. This build also exposes
some of the same data through an external OpenAPI server (§7) and an MCP
server, but local Ollama models proved **unreliable at invoking external
HTTP tools** — they'd describe a call, decline it, or ask a clarifying
question without ever actually issuing the request. Native in-process tools
don't have that failure mode. See `docs/db-to-ai-query-path.md` for the full
comparison. Prefer native tools unless a specific guide tells you otherwise.

### Step A — Make sure the tool can see its data (the mount)

Tools run **inside the container**, so whatever file a tool reads must be
bind-mounted into the container via a `Volume=` line in the Quadlet
(`~/.config/containers/systemd/open-webui.container`, generated from
`containers/open-webui.container`). This build's tool mounts:

```
# occupancy — read-write, NOT :ro. The occupancy DB is a live WAL database;
# a :ro mount can't create the required -wal/-shm sidecar files. The TOOL
# enforces read-only at the query level (PRAGMA query_only=ON) instead.
#
# ~/sovereign-sigint/db is a SYMLINK to this repo's own db/ directory
# (created/repaired by scripts/phase4-open-webui.sh), not a copy — this
# keeps the mount source stable and REPO_ROOT-independent while the
# container's view of the DB stays genuinely live. (An earlier version of
# this script `cp`'d the DB once at install time instead; that silently
# froze the tool's data at whatever the DB looked like the moment Phase 4
# ran, while the real producer kept growing the actual file underneath it.
# Fixed 2026-08-11 — if you're on an older checkout, re-run
# scripts/phase4-open-webui.sh to pick up the fix.)
Volume=%h/sovereign-sigint/db:/data/sigint

# Kismet — also read-write for the same WAL reason. ~/sovereign-sigint/kismet-data
# is likewise a symlink to this repo's kismet-data/ (where
# scripts/kismet-refresh.sh actually stages captures, via its --user timer
# from Phase 7). Do NOT point this at ~/kismet-captures — that was an
# earlier scratch path never wired to the refresh producer; using it here
# silently mounts an empty file and every kismet_summary call reports 0
# devices.
Volume=%h/sovereign-sigint/kismet-data:/data/kismet

# SigID reference — :ro IS correct here. Unlike the two above, this is a
# static directory of JSON files (the mirror); the sigid-mirror timer
# writes it on the HOST side, the tool only ever reads it.
# NOTE: /data is locked to o-rwx by default; the container runs the tool as
# a non-owner UID, so this specific path must be world-readable or the
# tool gets permission-denied. scripts/setup-data-dirs.sh already opens it
# (SigID is public reference data); if you built the tree by hand:
#   sudo chmod o+x /data /data/reference && chmod -R o+rX /data/reference/sigid
Volume=/data/reference/sigid:/data/sigid-ref:ro

# Whisper transcription — read-write. Shares the same host directory
# ai-ingest (Phase 5) reads from, so files the operator drops in — or that
# radiod's pcmrecord writes — are transcribable ad hoc from chat, not just
# on ai-ingest's 4-hour schedule.
Volume=/data/audio:/data/audio
```

(The operator-control tool, §6, has no data mount — it talks to the MCP
server over HTTP via `host.containers.internal:8140`, configured entirely
through its Valve, not the Quadlet.)

After editing the Quadlet template, reinstall and restart:

```
./scripts/phase4-open-webui.sh   # re-syncs the installed Quadlet from the repo template
systemctl --user daemon-reload
systemctl --user restart open-webui
```

Confirm from inside the container that the mount actually landed, and that
it matches the live host file (not a stale copy):

```
podman exec open-webui ls -la /data/sigint/
podman exec open-webui md5sum /data/sigint/occupancy.db
md5sum db/occupancy.db   # from the repo root — should match exactly
```

If the path isn't visible inside the container, or the checksums don't
match, no amount of tool/valve configuration will fix it — resolve the mount
first.

**Early-install note (before Phase 6):** you can install and test the
*tools* before real data exists. `scripts/setup-data-dirs.sh` pre-creates an
empty, schema-valid `occupancy.db`, so the occupancy tool opens cleanly and
returns "no signals recorded" rather than erroring — that confirms the tool
*fires*, distinct from confirming it has real data. The SigID and Kismet
tools will likewise return empty until their sources are synced/captured;
expected at this stage.

### Step B — Install the tool file

1. Open the tool's source: `cat openwebui-tools/<tool>.py` (or view it on
   GitHub).
2. In the UI: **Workspace → Tools → "+"** (Create New Tool).
3. Paste the **entire file**. Name/description auto-fill from the file's
   header docstring.
4. **Save**.

### Step C — Confirm the tool's Valve (its data path)

Each tool exposes a **Valve** — the path to its data *as seen from inside
the container*, matching the mount in step A. Open the tool's Valve settings
(gear icon on the tool card) and confirm — the shipped defaults already
match this build's mounts, so usually there's nothing to change, just
verify:

| Tool | Valve | Default |
|---|---|---|
| Occupancy | `DB_PATH` | `/data/sigint/occupancy.db` |
| Kismet | `KISMETDB_PATH` | `/data/kismet/latest.kismet` |
| SigID | `SIGID_METADATA_DIR` | `/data/sigid-ref/metadata` |
| Whisper | `AUDIO_ROOT` | `/data/audio` |
| Operator control | `MCP_BASE_URL` | `http://host.containers.internal:8140` (also requires `MCP_OPERATOR_TOKEN` — see §6) |

### Step D — Register a tool-capable Workspace model

A raw Ollama model picked straight from the chat dropdown has **no tool
configuration surface**. You need a Workspace model entry instead:

1. **Workspace → Models → "+"** (or edit an existing entry). Base it on
   **`qwen3:14b`** or **`llama3-groq-tool-use:8b`** — **never** `gemma3:12b`,
   which cannot call tools at all (§3).
2. **Untick the built-in capabilities** (notes/calendar/etc. default tool
   features). Left on, they can crowd out your custom tool.
3. Set **Function Calling = Native**. This is the setting that actually
   makes local models invoke tools reliably.
4. **Optional — attach the tool here** (tick your installed SIGINT tool[s]).
   This makes it available **by default in every chat** with this model — a
   convenience, not a requirement: you can instead (or additionally) enable
   it per-conversation in step E. Either path works; attaching here just
   saves re-toggling per chat.
5. **Save**.

### Step E — Enable the tool in the chat (Integrations)

**Required unless you attached the tool at the model level in D.** Open
WebUI gates tool availability **per conversation**. In the chat, open the
**Integrations** control (near the message box — a toggle or wrench/tools
icon depending on how many are installed) and turn **on** your SIGINT
tool(s) for that conversation.

If no tool is active for the chat — neither attached in D nor toggled on
here — the model genuinely has no access and will say so:
*"I don't have access to functions like query_occupancy…"* — which looks
exactly like a model that can't call tools, but is really a tool that just
isn't enabled for this conversation. Turn it on and the same model fires it
immediately. (If you attached it in D, it's already on here by default —
confirm via the same control if unsure.)

### Step F — Verify it fires

New chat → select your Workspace model → confirm the tool is enabled
(Integrations, or already attached) → give a **direct, explicit**
instruction. Explicit phrasing triggers tool calls far more reliably than a
terse question:

> Call radiod_status and report the totals.

Success looks like **"View Result from radiod_status"** (or the relevant
tool name) appearing in the chat, followed by the model answering from real
data. If instead it describes what it *would* do, or says it lacks the
capability, work through in order:

1. **Integrations toggle (E)** — the most common cause of "I don't have
   access to that function." The tool must be attached (D) *or* toggled on
   (E); if neither, the model cannot see it at all.
2. **Model config (D)** — is this a Workspace entry (not a raw Ollama
   model), built-ins unticked, Function Calling = Native?
3. Ask *"What tools do you have available?"* — nothing listed means it's not
   reaching the chat (repeat 1/2); listed but never called means try the
   explicit "Call X and report Y" phrasing.
4. If the tool **fires but errors** opening its data, that's the **mount**
   (A) or the **Valve** (C) — not the tool code.

---

## 6. The tools this build installs

Install each via §5's procedure. Every file lives in `openwebui-tools/`.

- **Occupancy** (`sigint_occupancy_tool.py`) — what's active on the RF
  bands, from your SDRs, via the radiod-fed occupancy DB. See
  `docs/db-to-ai-query-path.md`.
- **Kismet** (`sigint_kismet_tool.py`) — WiFi access points/clients seen.
  See `docs/kismet-to-ai-bridge.md`.
- **SigID reference** (`sigid_reference_tool.py`) — what a signal *is*, from
  the mirrored sigidwiki catalog. See the vision guide for the
  identification workflow that ties this to a live waterfall.
- **Whisper transcription** (`sigint_whisper_tool.py`) — ad-hoc GPU
  transcription/translation of a single audio file at chat time (QSO
  recordings, demodulated voice, broadcast/utility audio), distinct from
  ai-ingest's scheduled background pass over the same `/data/audio`
  directory. Requires `faster-whisper>=1.0.0` in the tool's `requirements:`
  frontmatter (Open WebUI installs it automatically on first load).
- **Operator control** (`sigint_operator_tool.py`) — changes SDR
  frequency/mode via the MCP control plane. **Restricted**, not a read-only
  query tool: it requires an `MCP_OPERATOR_TOKEN` Valve set from
  `~/.config/sigliere/mcp.env`'s `SIGLIERE_MCP_TOKENS_JSON`, and every call
  is gated in code to members of the Open WebUI **Operator** group or full
  admins (`ALLOW_ADMIN_ROLE` Valve, default on) — checked fresh on every
  call, not cached. Read the tool file's header comment before installing;
  this one has real access-control implications the read-only tools don't.

---

## 7. Optional: External OpenAPI connection (current occupancy path)

This build also exposes occupancy/radiod read-only functions through an
external OpenAPI server, `openapi-tools/sigint_openapi_server.py` — separate
from, and in addition to, the native occupancy tool in §6. Prefer the native
tool (§5) for anything you rely on; use this connection type mainly for
tooling that specifically expects an OpenAPI-shaped connection.

### Steps

1. **Admin Panel → Settings → Connections → Add Connection**, Type =
   **OpenAPI**.
2. **URL**: `http://<box-lan-ip>:8130`.
3. **OpenAPI Spec URL**: `http://<box-lan-ip>:8130/openapi.json`.
4. **Auth**: **None** (current `sigint-openapi-tools.service` deployment has
   no auth layer).

`scripts/openwebui-openapi-command.sh` prints these exact values, pre-filled
with the box's LAN IP.

**Do not mix MCP and OpenAPI endpoints in one connection.** If Type is
OpenAPI, both URL fields must target the OpenAPI server (`:8130`) — never the
MCP server (`:8140`), which is a different protocol entirely.

## Optional: the Knowledge (RAG) feature

Separate from native tools, Open WebUI's **Knowledge** feature does
retrieval-augmented generation over uploaded documents, using
`nomic-embed-text` (§3). It has its own full walkthrough in
`docs/rag-knowledge-base-guide.md`. For this build's own live data
(occupancy, SigID), prefer the native tools in §6 — they query current data
directly, where Knowledge is snapshot-based against whatever was uploaded.

---

## Troubleshooting: gotchas learned building this

- **`gemma3:12b` cannot call tools at all.** A real Ollama limitation, not a
  misconfiguration. Use `qwen3:14b` or `llama3-groq-tool-use:8b` for
  anything tool-driven; reserve `gemma3:12b` for image turns (vision
  guide's two-model workflow).
- **Built-in capabilities left ticked** on a Workspace model silently
  crowd out custom tools — untick them (§5 step D.2).
- **Terse questions don't trigger tools reliably.** "Call `<tool>` and
  report …" does (§5 step F).
- **A tool that's never worked since install** is almost always not enabled
  for the conversation — attach it to the Workspace model (D) or toggle it
  in the chat's Integrations (E). It's rarely the tool code itself.
- **A tool that fires but errors** reading its data is the mount (§5 step A)
  or the Valve (§5 step C) — confirm the container-visible file actually
  matches the live host file via `md5sum`, not just that the path exists.
- **A previously-installed occupancy/Kismet tool answering suspiciously
  stale data** — if you're on a checkout older than 2026-08-11, your
  `~/sovereign-sigint/db` or `~/sovereign-sigint/kismet-data` may be a real
  (non-symlink) directory holding a frozen one-time copy rather than a
  symlink to this repo's live data. Re-run
  `scripts/phase4-open-webui.sh` — it now detects and repairs this (see §5
  step A's mount comments), or fix by hand:
  `rm -rf ~/sovereign-sigint/db && ln -s <repo>/db ~/sovereign-sigint/db`
  (same pattern for `kismet-data`).
- **If the UI itself won't load**, check the services, not the browser:
  `systemctl --user status open-webui` and `systemctl --user status caddy`
  (§1.1).
