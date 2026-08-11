# Setting Up Open WebUI — The Sovereign AI Front End

Open WebUI is the chat interface for this build's local AI: it talks to the
local Ollama models and hosts the **native tools** that let the model query
your own SIGINT data (occupancy, Kismet, SigID, audio, SDR control). Every
other AI guide in this repo assumes Open WebUI is up and a tool is installed
the way this guide describes. Start here.

## Orientation: where things live in 0.11.0

Getting the two-menu mental model right up front avoids hunting.

- **Workspace** (left sidebar) → **Models**, **Tools**, **Prompts**,
  **Knowledge**. This is where you register a model for tool use, install
  native tools, add saved prompts, and manage RAG collections. Everything in
  §5 and §6 happens here.
- **Admin Panel** (user-menu avatar, bottom-left) → **Settings** →
  **Connections / Models / Tools**. Server-wide configuration: the Ollama
  connection (§3A) and bulk model management live here.
- The **chat view** has a model selector at the top and, once a tool is
  enabled for the conversation, an **Integrations** control near the message
  box (§5 step E) — this is the per-chat tool on/off switch.

## First boot: create the admin account

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

## Pull the models

### Steps

1. Open a **New Chat** and notice the modesl available in the lower right part of the chat window. Validate the following models are available:

- qwen3:14b
- llama3-groq-tool-use:8b
- gemma3:12b
- nomic-embed-text

If the models do not exists, pull them from a host shell:

```
ollama pull qwen3:14b
ollama pull llama3-groq-tool-use:8b
ollama pull gemma3:12b
ollama pull nomic-embed-text
```

### SIGINT Models
`Workspace → Models` is a **workspace model registry**, not an auto-populated
list of every Ollama model you've pulled. Seeing `0` there is expected until you
deliberately create a Workspace model entry for one of the discovered Ollama
models above and it's where you'll register `qwen3:14b` (or `llama3-groq-tool-use:8b`)
for tool use specifically.


## Installing native tools

### Steps

1. Open the SIGID Reference tool source and copy it.
```
cat ~\sigliere\openwebui-tools\sigid_reference_tool.py
```

2. In the UI: **Workspace → Tools → "+"** (Create New Tool).

3. Remove existing content and paste the **entire file**. Name/description auto-fill from the file's header docstring.
   
4. **Save**.

5. Repeat Steps 1-3 for the following tools in `~\sigliere\openwebui-tools`
```
sigint_kismet_tool.py
sigint_occupancy_tool.py
sigint_whisper_tool.py
```

6. Open the tool's Valve settings (gear icon on the tool card) and confirm 
the shipped defaults already match this build's mounts:

| Tool | Valve | Default |
|---|---|---|
| Occupancy | `DB_PATH` | `/data/sigint/occupancy.db` |
| Kismet | `KISMETDB_PATH` | `/data/kismet/latest.kismet` |
| SigID | `SIGID_METADATA_DIR` | `/data/sigid-ref/metadata` |
| Whisper | `AUDIO_ROOT` | `/data/audio` |

**Why native, not external OpenAPI/MCP:** a "native tool" is one of this
repo's Python files in `openwebui-tools/` that runs **in-process inside the
Open WebUI container** and reads your data directly. This build also exposes
some of the same data through an external OpenAPI server and an MCP
server, but local Ollama models proved **unreliable at invoking external
HTTP tools** — they'd describe a call, decline it, or ask a clarifying
question without ever actually issuing the request. Native in-process tools
don't have that failure mode. See `docs/db-to-ai-query-path.md` for the full
comparison. Prefer native tools unless a specific guide tells you otherwise.

## Create a Workspace model that is tool-capable

### Steps

A raw Ollama model picked straight from the chat dropdown has **no tool
configuration surface**. You need a Workspace model entry instead:

1. **Workspace → Models → "+"** (or edit an existing entry). Base it on
   **`qwen3:14b`**.
2. **Untick the built-in capabilities** (notes/calendar/etc. default tool
   features). Left on, they can crowd out your custom tool.
3. Set **Function Calling = Native**. This is the setting that actually
   makes local models invoke tools reliably.
4. **Attach the tool here** (tick your installed SIGINT tool[s]).
   This makes it available **by default in every chat** with this model
5. **Save**.

## Verify it fires

New chat → select your Workspace model → confirm the tool is enabled
(Integrations, or already attached) → give a **direct, explicit**
instruction. Explicit phrasing triggers tool calls far more reliably than a
terse question:

> Call radiod_status and report the totals.

Success looks like **"View Result from radiod_status"** (or the relevant
tool name) appearing in the chat, followed by the model answering from real
data. 

## The tools this build installs

Every file lives in `openwebui-tools/`.

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

## Optional: External OpenAPI connection (current occupancy path)

This build also exposes occupancy/radiod read-only functions through an
external OpenAPI server, `openapi-tools/sigint_openapi_server.py` — separate
from, and in addition to, the native occupancy tool. Prefer the native
tool for anything you rely on; use this connection type mainly for
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

