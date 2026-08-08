# Open WebUI Role Provisioning — analyst / operator

**Status as of 2026-08-08:** confirmed running **Open WebUI 0.11.0**.
Token infrastructure, both connections (analyst + operator), and a CORS
bug that was blocking the browser from reaching the MCP server are all
live and operator-confirmed working (see `docs/mcp-validation-evidence.md`'s
2026-08-08 entries — search for "CORS Bug" for the connection fix). What's
**left**: creating the two Open WebUI Groups and scoping each connection's
visibility to its group (Steps 2–3 below). That needs the operator's
Admin Panel login — no agent working on this repo has (or should have)
that login; see Guardrail 7 in the project handoff doc.

Steps 0–1 below are pinned to this specific 0.11.0 build, verified by
reading its installed source in the running container
(`podman exec open-webui ...` against `/app/backend/open_webui/`), not
guessed from generic Open WebUI docs — see the file/line citations
throughout.

## Step 0 — Generate the two connection blocks

0.11.0's Admin Panel only offers **Type = OpenAPI** for tool server
connections (no MCP/Streamable HTTP option in this build — confirmed by
the operator's own UI and by the absence of an MCP entry point in that
form). The MCP server is a FastAPI app and already serves its own
`/openapi.json`, so register it as an OpenAPI connection instead:

```bash
bash scripts/openwebui-mcp-openapi-command.sh
```

prints one paste-ready block for **analyst** and one for **operator**
(`Type: OpenAPI` / `Name` / `URL` / `OpenAPI Spec URL` / `Auth: Bearer` +
token), each carrying its own real bearer token pulled live from
`~/.config/sigliere/mcp.env`'s `SIGLIERE_MCP_TOKENS_JSON`. Pass `analyst`
or `operator` as an argument to print just one block.

(There is also `scripts/openwebui-mcp-command.sh`, which prints
`Type: MCP / Streamable HTTP` blocks — keep that around in case a future
Open WebUI upgrade adds native MCP connection support, per
`docs/openapi-to-mcp-migration.md`, but it's not usable on this build.)

## Step 1 — Register both as separate connections in Open WebUI (done, confirmed 2026-08-08)

**Admin Panel → Settings → Tools → Tool Servers** (confirmed exact label:
the string `"Tool Servers"` is in this build's compiled frontend) → add a
connection for each of the two Step 0 blocks. In the "Edit Connection"
form: `URL` = the base URL, `Auth` = `Bearer` + the token, then under
**Advanced → OpenAPI Spec URL** = the `/openapi.json` URL. You should end
up with two distinct entries, e.g. "SIGINT MCP (Analyst)" and
"SIGINT MCP (Operator)" — do **not** merge them into one connection with
one token; the whole point is that they carry different tokens.

If this shows **"Failed to connect to ... OpenAPI tool server"**: that
was a real bug (CORS preflight `OPTIONS /openapi.json` getting FastAPI's
default `405`, blocking the browser before the real request ever went
out — non-browser tests like `curl` never hit it, which is what made it
look like a reachability problem at first). Fixed server-side in
`mcp-server/src/sigliere_mcp_server.py` and confirmed working
2026-08-08 — see the evidence log. If you hit connection failures again,
check `journalctl --user -u sigliere-mcp` for `OPTIONS ... 405` lines and
`journalctl --user -u open-webui` for context first, rather than assuming
it's a token or URL typo.

## Step 2 — Create the two groups

**Admin Panel → Users → Groups** → **"Create Group"** button (confirmed
exact label in this build's frontend). Create:
- `analyst` — read-only MCP access
  (`mcp_list_nodes`, `mcp_route_frequency`, `mcp_radiod_status`).
- `operator` — read + tuning access (adds `mcp_set_frequency` /
  `POST /set_frequency`). Approved radio operators only.

Name and description are the only required fields; leave "Permissions"
at its defaults (that field controls group-wide feature access like chat
sharing, not per-connection visibility — see Step 3). Add members from
each group's own page after creating it.

## Step 3 — Scope each connection to its group

**Important, verified against this build's source (was wrong in an
earlier draft of this doc):** a Tool Server connection with **no access
grants configured is private — visible to admins only**, not public to
everyone by default
(`open_webui/utils/access_control/__init__.py`'s `has_connection_access`:
"Missing, None, or empty access_grants → private, admin-only"). So **both**
connections need an explicit grant, or non-admin users will see neither
one, analyst included:

- "SIGINT MCP (Analyst)" connection → grant read access to the `analyst`
  group.
- "SIGINT MCP (Operator)" connection → grant read access to the
  `operator` group only.

Look for an **"Access Control"** control on each connection in the Tool
Servers list (confirmed string exists in this build; it's the same
sharing mechanism Open WebUI uses for Models/Knowledge elsewhere — a
lock/share icon, Private vs. custom-access with a group/user picker).
Exact icon placement on the Tool Servers list row isn't independently
screenshotted in this doc — if you can't find it from the list view, try
each connection's own edit dialog.

**What it's actually setting, if you want to verify directly:** each
connection is one entry in `Config['tool_server.connections']`
(`GET /api/v1/configs/tool_servers` as an admin). The access state lives
at `connection.config.access_grants`, a list of grant objects shaped like
`{"principal_type": "group", "principal_id": "<group-id>", "permission": "read"}`.
Group IDs come from `GET /api/v1/groups/` (also admin-only). If the UI
control is ever hard to locate, an admin with a personal API key (**user
menu → Settings → Account → API Keys**, not tested against this build by
this agent — verify it exists there before relying on it) could set this
directly via `POST /api/v1/configs/tool_servers` with the full
`TOOL_SERVER_CONNECTIONS` list (including the untouched entries — this
endpoint replaces the whole list, it doesn't patch one entry) carrying
the updated `access_grants`. This fallback is **unverified** — worked out
by reading the source, not exercised live, since this agent has no Open
WebUI login. Prefer the UI path; only reach for this if the UI control
genuinely can't be found.

## Step 4 — Assign users

Default users → `analyst` group. Add someone to `operator` only against a
documented change request (Prompt 3 below) — this is an access-escalation
decision, not a routine one.

## Defense in depth, not the only gate

Steps 1–3 control what a user sees/can attach in Open WebUI's UI. The
actual authorization boundary is enforced **server-side**, independent of
Open WebUI: `sigliere_mcp_server.py`'s `require_role`/`_mcp_auth` reject
`set_frequency`/`mcp_set_frequency` for any token whose mapped role isn't
`operator`, regardless of which connection or client called it. Confirmed
live 2026-08-08, server still in dry-run mode:

| Token role | `POST /set_frequency` | 
|---|---|
| analyst | **403** (role analyst lacks operator permission) |
| operator | **200** |

So a misconfigured or skipped Step 3 is a usability/exposure problem (an
analyst could see a connection meant for operators, or — per the
corrected default above — nobody but the admin sees either connection),
not a safety hole: the server refuses the tuning call either way.

---

## Policy prompts (source of intent for the steps above)

### Prompt 1: analyst role

Create a role named analyst.
Grant analyst access to Sigliere MCP read-only tools only:
- mcp_list_nodes
- mcp_route_frequency
- mcp_radiod_status
Deny access to mcp_set_frequency.

### Prompt 2: operator role

Create a role named operator.
Grant operator access to all Sigliere MCP tools:
- mcp_list_nodes
- mcp_route_frequency
- mcp_radiod_status
- mcp_set_frequency

### Prompt 3: user assignment policy

Assign default users to analyst role unless there is an explicit operational requirement.
Only approved radio operators may be assigned to operator role.
Require a documented change request before operator role assignment.

### Prompt 4: token handling policy

Store analyst and operator bearer tokens separately.
Rotate operator tokens on schedule and after staffing changes.
Never paste operator tokens into shared channels or role descriptions.

`~/.config/sigliere/mcp.env` is already `0600` (owner-only). The "store
separately" intent is really about where the *operator* token ends up
being pasted in Open WebUI — Step 1's two-connection split keeps it out of
the analyst-visible connection entirely, so it's never sitting in a tool
description or config surface analyst-group users can read.
