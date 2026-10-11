# MCP server design (proposal)

Status: **design approved; Phase 0 (server and tests) implemented, not yet
deployed.** Branch `MCP-Server`. Decisions approved: the scope and security
model below, plus recommendations 1, 2, and 3 from section 10. It follows the
"Option A" work (`sigliere_core`, [tool-development.md](tool-development.md)),
which was done first because the MCP server is a second set of thin wrappers
over the same core.

## 1. Why

The data-source tools (Kismet, occupancy, SigID, MAC vendor) currently run
*inside* the Open WebUI process. That has three costs:

1. **Open WebUI holds filesystem access to the data.** The container mounts
   `/data/occupancy`, `/data/kismet-bridge`, and the reference mirrors
   (read-only) so the in-process tools can open them. A tool bug or a
   compromised Open WebUI therefore reaches the data directly.
2. **The tools are locked to Open WebUI.** They use its `Tools`/valves
   convention, are installed by pasting into the UI, and can be used by no
   other client (for example a future scheduled-analysis service).
3. **Guidance lives in the system prompt.** Per-tool rules ("call
   `kismet_summary` first", "ADS-B is excluded unless...") sit in the global
   prompt and grow with every tool.

An MCP server moves the data access into one small, separately sandboxed
service, makes the tools reusable, and lets tool descriptions carry their own
usage guidance.

## 2. Non-goals

- **Not a replacement for the core path.** Gateway status and operator tuning
  stay native Open WebUI tools. The core install (Ollama, gateway, Open WebUI,
  Caddy) must keep working with no MCP service present.
- **No control.** The MCP server never tunes a receiver, never holds the
  operator token, and never writes to any database.
- **No new ingress.** Nothing here is reachable from the LAN.
- **No third-party MCP servers or skills.** Only code in this repository.

## 3. What was verified in the running Open WebUI (v0.12.0)

These facts come from inspecting the pinned image, not documentation:

| Fact | Consequence |
|---|---|
| The MCP client is in the backend (`open_webui/utils/mcp/client.py`) and uses `mcp.client.streamable_http.streamablehttp_client`. | The **Open WebUI server** makes the calls, not the browser. A loopback URL works; no browser route is needed. |
| Connection auth types: `bearer` (default), `none`, `session`, `system_oauth`, `oauth_2.1`. | A **static bearer token** is supported. No OAuth machinery needed. |
| Per-connection `function_name_filter_list` restricts which tool names are exposed. | A second, independent allow-list on the Open WebUI side (defense in depth). |
| `has_connection_access` gates a connection per user/group. | The MCP connection can be limited to analyst users. |
| The image ships `mcp` **1.27.2**. | Pin the server to the same SDK version to avoid protocol drift. |
| `ENABLE_TOOL_SERVERS` defaults to true; `ENABLE_DIRECT_CONNECTIONS` defaults to false. | Keep direct (browser-side) connections **off**. |

Not yet verified (see section 10): exact tool-name exposure to the model,
output-format token cost, and behavior behind the Caddy proxy.

## 4. Architecture

```text
Open WebUI (127.0.0.1:8080)
    |  streamable HTTP, Authorization: Bearer <MCP token>
    v
Caddy private router (127.0.0.1:8180)
    |-- /ollama  -> Ollama            (existing)
    |-- /gateway -> SIGedge gateway   (existing)
    '-- /mcp     -> sigliere-mcp 127.0.0.1:8150   (new)

sigliere-mcp (rootless Podman, read-only data mounts)
    |-- /data/kismet-bridge  :ro
    |-- /data/occupancy      :ro
    |-- /data/reference/sigid, /data/reference/mac-vendors  :ro
    (no gateway token: it reads local mirrors only)
```

Properties:

- Binds `127.0.0.1:8150`. Reached only through Caddy's loopback router on
  8180, matching how `/ollama` and `/gateway` already work. Port 8443 stays
  the sole LAN ingress.
- After migration, Open WebUI **no longer mounts** the occupancy, Kismet,
  SigID, or MAC data. Only `/data/audio` (Whisper) remains. This is the main
  security gain: the web-facing process loses direct data access.
- The server is **stateless**: no MCP sessions, JSON responses. All tools are
  read-only queries, so there is nothing to keep between calls.

## 5. Scope: what moves and what stays

| Tool | Where | Reason |
|---|---|---|
| Kismet (`query_wifi_devices`, `kismet_summary`) | **MCP** | Read-only mirror query |
| Occupancy (`query_occupancy`, `occupancy_sightings`, `occupancy_summary`) | **MCP** | Read-only mirror query |
| SigID (`lookup_signal`, `search_signals`) | **MCP** | Read-only reference |
| MAC vendor (`lookup_mac_vendor`, `search_mac_vendors`) | **MCP** | Read-only reference; the 58k-entry index is cached once in a long-lived process |
| SIGedge status (`list_sigedge_nodes`, `sigedge_status`) | **Native** (revisit later) | It is part of the core path, which must not depend on an optional service, and moving it would give the MCP server a gateway token |
| Operator control (`list_controllable_nodes`, tune) | **Native, permanently** | Its live Open WebUI group-membership check cannot be reproduced outside Open WebUI |
| Whisper transcription | **Native** | Needs audio file access and a GPU/model in the Open WebUI container |

Tool names and parameters are kept identical so the system prompt and any
saved model configuration keep working.

## 6. Security model

### New trust boundary

One new service. If it were compromised an attacker would get read access to
the four mirrors (already readable by Open WebUI today). It holds **no gateway
token of any kind**, because the tools read local databases and files only, so
it has no path to SIGedge. Net exposure is smaller than today: the same data,
moved out of the web-facing process, with no credentials beside its own.
If status ever moves to MCP (open question 5) it would receive the gateway
**analyst** token only, never the operator token.

### Controls

| Control | Detail |
|---|---|
| Network | Loopback only; Caddy private router; no LAN exposure. |
| Authentication | Dedicated MCP bearer token (not a gateway token), checked by ASGI middleware with a constant-time compare. Missing/invalid token returns 401 before any MCP handling. |
| Token handling | `~/.config/sigliere/mcp.env`, mode 0600, generated once and preserved on re-runs (same pattern as `gateway.env`). It contains only the MCP token. No gateway token is copied into it. |
| Least privilege | Read-only mounts (`:ro`); rootless Podman; SQLite opened with `mode=ro`; no shell, filesystem, or network tools. |
| Host-header validation | Enable the SDK's DNS-rebinding protection with allowed hosts limited to the loopback names Caddy forwards (`127.0.0.1:8180`, `127.0.0.1:8150`). |
| Open WebUI side | Connection created by an admin; `function_name_filter_list` set to the exact tool names; access limited to analyst users; direct connections stay disabled. |
| Supply chain | One pinned dependency (`mcp==1.27.2`, matching Open WebUI) plus `sigliere_core`. No external servers. |

### Prompt injection from RF data

Tool results contain attacker-influenced strings: SSIDs, device names, and
wiki text can carry instructions aimed at the model. This risk already exists
with the native tools and MCP does not change it, but it is worth stating:
the MCP tools can only read, so the exposure is to the model's *answers*.
The real risk is a model session that also has the operator tool attached. The
existing mitigations apply and should stay: the operator tool's group check,
dry-run default, and the system-prompt rule to tune only on explicit user
request. Recommended practice: do not attach the operator tool to the general
analysis model.

## 7. Layout

```text
mcp_server/                      (not `mcp/`: that name would shadow the `mcp` SDK on sys.path)
  Containerfile                  python:3.12-slim; pip install mcp==1.27.2; copies sigliere_core   [Phase 1]
  requirements.txt
  src/sigliere_mcp/
    server.py                    FastMCP app; streamable HTTP; stateless; JSON responses
    config.py                    env: data paths, token file, bind address
    auth.py                      bearer-token ASGI middleware
    tools/
      kismet.py                  @mcp.tool wrappers over sigliere_core.kismet
      occupancy.py
      sigid.py
      mac.py
containers/sigliere-mcp.container    [Phase 1] Quadlet, data mounts :ro, host network, 127.0.0.1:8150
scripts/install-sigliere-mcp.sh      [Phase 1] build image, create mcp.env, install Quadlet
scripts/validate-sigliere-mcp.sh     [Phase 1] initialize + tools/list + one call per tool
tests/test_mcp_server.py             in-process client, HTTP auth, and native-parity tests
docs/mcp-server-design.md            this file
```

Details that need care:

- **Path prefix.** Caddy's `handle_path /mcp/*` strips the prefix, so the
  server must serve its MCP endpoint at `/` (`streamable_http_path="/"`).
  Open WebUI's connection URL is `http://127.0.0.1:8180/mcp`.
- **Streaming.** The Caddy route needs `flush_interval -1` on the
  `reverse_proxy` so responses stream.
- **Caddyfile ownership.** The private router is generated by
  `install-open-webui.sh`. Proposal: always emit the `/mcp` handle there.
  With no service installed it returns 502 on a loopback-only port, which is
  harmless, and it avoids a second Caddyfile generator.
- **Wrappers stay thin.** Each tool is a typed function: open the database
  with `connect_ro`, call the `sigliere_core` function, return data. Docstrings
  are carried over from the native tools and become the tool descriptions.
- **Core modules are inlined, not imported, only for Open WebUI.** The MCP
  image has the repository's `sigliere_core` copied in and imports it
  normally; the build-script inlining is unnecessary here.

## 8. Migration plan

**Phase 0: skeleton and tests (done).** Server, auth middleware, and the four tool
modules, with in-process tests: the SDK client against the app, auth rejected
without a token, read-only enforcement, results equal to the native tools on
the shared fixtures.

**Phase 1: deploy beside the native tools.** Installer, Quadlet, Caddy route,
validator. Add the MCP connection in Open WebUI with the function filter. Both
paths exist; use a test model that has only the MCP tools attached.

**Phase 2: compare.** Run the same questions against the native-tools model
and the MCP-tools model with `qwen3:14b`. Record tool-call success, answer
equality, and prompt token cost (tool schemas count against the 16k context
already needed for the native set). Exit criterion: no regression on the
Kismet/MAC/SigID/occupancy question set.

**Phase 3: cut over.**
- Detach the native copies from models; re-test.
- Remove the occupancy, Kismet, SigID, and MAC `Volume=` lines from
  `containers/open-webui.container`; keep `/data/audio`.
- Trim the per-tool paragraphs from the system prompt into tool descriptions.
- Amend the "no MCP" rule (section 9) and update `PROJECT_STATE.md`.
- Decide the fate of `openwebui-tools/src/` and the build script: keep them as
  a fallback for one release, then remove them if unused. The core stays.

**Rollback** at any phase: disable the connection in Open WebUI and re-attach
the native tools. Their files stay in the repository until Phase 3 is proven.

## 9. Rule amendments

These documents currently forbid MCP and would change in Phase 3:

- `docs/architecture.md` (boundaries list): replace "There is no parallel
  external OpenAPI or MCP query service." with "MCP is permitted only as the
  loopback `sigliere-mcp` service behind Caddy's private router: read-only,
  holding no gateway credentials, optional. There is no external OpenAPI or
  MCP query service."
- `PROJECT_STATE.md` ("Fixed architecture and security rules"): same wording.
- `docs/openwebui-setup.md`: replace "No external OpenAPI or MCP connection is
  required" with instructions for the optional `sigliere-mcp` connection.
- `docs/optional-tools.md`, `docs/operations.md`, `INSTALL.md`: install,
  token rotation, and upgrade steps for the MCP service.

## 10. Open questions and recommendations

| # | Question | Recommendation |
|---|---|---|
| 1 | **Output format.** MCP tools can return text, structured content, or both. Both would roughly double tokens if the client forwards both to the model. | **Approved and implemented.** Compact JSON text only (`structured_output=False`); failures use `isError`. A test asserts each result is a single text block with no structured duplicate. |
| 2 | **Tool-name exposure.** Does v0.12 prefix MCP tool names? If not, native and MCP tools with identical names collide on a model that has both. | **Approved.** Verify in Phase 1. Use separate test models until Phase 3, so no model has both sets. |
| 3 | **Behind-Caddy behavior.** Host-header handling, streaming flush, and request timeouts through the proxy. | **Approved.** Verify in Phase 1 with the validator; set generous timeouts for the MAC first-load. The Host check itself is already tested (see section 12). |
| 4 | **Where the Open WebUI connection is configured.** Admin UI (stored in Open WebUI's database, as tool valves are today) versus `TOOL_SERVER_CONNECTIONS` env on first start. | Admin UI, documented in setup. Environment seeding only applies on first start and would put a token in a unit file. |
| 5 | **Status tool.** Move it to MCP later? | Not initially. Revisit after the cutover; the core path stays independent. Moving it would add the gateway analyst token to `mcp.env`, which is the main reason to leave it native. |
| 6 | **Scheduled analysis.** The deferred "proactive watch service" idea would also be an MCP client. | Out of scope here. The reuse is a reason to do this first. |
| 7 | **Native fallback.** Keep `openwebui-tools/src/` and the build script after cutover? | Keep for one release, then drop. |
| 8 | **Docs and prompt trimming.** Exactly which sentences of the system prompt move into tool descriptions. | Decide in Phase 2 using the comparison results. |

## 11. Acceptance criteria

- `validate-sigliere-mcp.sh` passes: initialize, list exactly the expected
  tool names, one successful call per tool, 401 without or with a wrong token.
- Nothing listens on a non-loopback address; only 8443 is LAN-reachable
  (`validate-security-hardening.sh` and `validate-tiered.sh` still pass).
- The MCP container has no write mounts and no gateway token.
- The comparison question set shows no regression on `qwen3:14b`.
- After Phase 3, Open WebUI mounts only `/data/audio` from the data tree.
- Documents in section 9 updated; the unit-test suite (including new MCP
  tests) passes.

## 12. Phase 0 results

Implemented in `mcp_server/src/sigliere_mcp/` with 24 tests in
`tests/test_mcp_server.py`:

- **Config** refuses a missing or short (under 32 characters) token and refuses
  any non-loopback bind address; the token is excluded from `repr`.
- **Auth** is a pure ASGI bearer gate with a constant-time compare. Missing,
  wrong, truncated, extended, empty, and non-Bearer credentials all return 401
  with `WWW-Authenticate: Bearer` before any MCP handling, and the 401 body
  never contains the token.
- **Host validation.** Requests whose `Host` is not an allowed loopback name
  are rejected (400/421); the Caddy-forwarded `127.0.0.1:8180` is accepted. A
  test server on an unlisted port was rejected with 421, confirming the check
  is live.
- **Tools.** Exactly the nine expected tools, every one annotated read-only and
  non-destructive, with per-parameter descriptions in the schema. No-match
  results are normal text; unreadable data is a protocol error (`isError`).
- **Parity.** On shared fixtures, every tool's output equals the native Open
  WebUI tool's output (parsed JSON equal; prose results identical).
- **Environments.** The suite passes on the bare host (MCP tests skipped), in a
  venv with `mcp==1.27.2`, and inside the Open WebUI v0.12.0 image (its bundled
  `mcp` 1.27.2).
- **End to end.** A real server process was driven with the same client class
  Open WebUI uses (`streamablehttp_client`): 401 without a token, nine tools
  listed, a vendor lookup returned correctly, and the server bound
  `127.0.0.1` only.

Not yet done: the container image, Quadlet, Caddy route, installer and
validator (Phase 1), and anything involving the live Open WebUI.
