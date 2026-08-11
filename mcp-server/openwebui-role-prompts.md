# Open WebUI Role Provisioning — analyst / operator

**Status as of 2026-08-11:** running **Open WebUI 0.11.0**. Read-only
access (analyst) is a registered OpenAPI Tool Server connection, done and
working. Tuning access (operator) is **not** a connection at all — it's a
native in-process tool that checks the calling user's group membership in
code — because the approach this doc originally described (scope a shared
connection to a group) turned out not to exist in this build. See
"History: why this doc changed" below before reusing that old approach
for anything else.

`SIGLIERE_MCP_DRY_RUN` is currently `false` (production) — see
`docs/mcp-validation-evidence.md`'s 2026-08-11 entries for the full flip
history, including a mid-session revert back to dry-run while the gap
below was open.

## Step 0 — Generate the analyst connection block

0.11.0's Admin Panel only offers **Type = OpenAPI** for tool server
connections (no MCP/Streamable HTTP option in this build — confirmed by
the operator's own UI and by the absence of an MCP entry point in that
form). The MCP server is a FastAPI app and already serves its own
`/openapi.json`, so register the **analyst** endpoint as an OpenAPI
connection:

```bash
bash scripts/openwebui-mcp-openapi-command.sh analyst
```

prints one paste-ready block (`Type: OpenAPI` / `Name` / `URL` /
`OpenAPI Spec URL` / `Auth: Bearer` + token), carrying the real analyst
bearer token pulled live from `~/.config/sigliere/mcp.env`'s
`SIGLIERE_MCP_TOKENS_JSON`.

**Do not also generate/register an `operator` connection this way** — see
Step 2. `scripts/openwebui-mcp-openapi-command.sh operator` still works
and still prints a valid block (useful for the CLI / `operator_cli.py`
path, or for direct `curl` testing), but pasting it into Admin Panel ->
Tool Servers is exactly the setup that was tried and removed — read on
before doing that again.

(There is also `scripts/openwebui-mcp-command.sh`, which prints
`Type: MCP / Streamable HTTP` blocks — keep that around in case a future
Open WebUI upgrade adds native MCP connection support, per
`docs/openapi-to-mcp-migration.md`, but it's not usable on this build.)

## Step 1 — Register the analyst connection (done, confirmed 2026-08-08)

**Admin Panel → Settings → Tools → Tool Servers** (confirmed exact label:
the string `"Tool Servers"` is in this build's compiled frontend) → add
the Step 0 block. In the "Edit Connection" form: `URL` = the base URL,
`Auth` = `Bearer` + the token, then under **Advanced → OpenAPI Spec URL**
= the `/openapi.json` URL. You should end up with one entry, e.g.
"SIGINT MCP (Analyst)".

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

There is (as of 2026-08-11) **no "SIGINT MCP (Operator)" connection** —
it was created, then deleted once the access-control gap below was
found. Do not re-create it without solving that gap again first.

## Step 2 — Create the two groups (done, confirmed 2026-08-11)

**Admin Panel → Users → Groups** → **"Create Group"** button. This repo's
actual groups, confirmed live against the running database:
- `Analyst` — read-only MCP access
  (`mcp_list_nodes`, `mcp_route_frequency`, `mcp_radiod_status`), via the
  Step 1 connection.
- `Operator` — tuning access, via the native tool in Step 3, not a
  connection. Approved radio operators only.

(Capitalization matters if you're checking membership in code —
`openwebui-tools/sigint_operator_tool.py`'s group-name compare is
case-insensitive as a safety net, but match the real names above rather
than relying on that.)

Name and description are the only required fields; leave "Permissions" at
its defaults (that field controls group-wide feature access like chat
sharing and the `Direct Tool Servers` on/off switch — see "History"
below — not per-connection visibility, which doesn't exist as a control
in this build). Add members from each group's own page after creating it.

## Step 3 — Install the operator tool (replaces the old "scope the connection" step)

Instead of restricting a shared connection (not possible in this build —
see History), operator access is a **native Python tool** that checks who's
asking on every single call, in code, using Open WebUI's own internal
Groups model — verified live against this host's installed
`open_webui/models/groups.py`.

1. **Workspace → Tools → "Create new tool"** → paste in the full contents
   of `openwebui-tools/sigint_operator_tool.py`.
2. Open its **Valves** (gear icon) and set `MCP_OPERATOR_TOKEN` to the
   operator token from `~/.config/sigliere/mcp.env`'s
   `SIGLIERE_MCP_TOKENS_JSON`. Every method in the tool fails closed
   (refuses) if this is empty — it does not fall back to a weaker check.
   Leave `MCP_BASE_URL` and `OPERATOR_GROUP_NAME` at their defaults —
   both confirmed correct for this host as of 2026-08-11.
3. `ALLOW_ADMIN_ROLE` (default `true`): any Open WebUI account with
   `role=admin` may use the tool even if not personally in the `Operator`
   group, checked against Open WebUI's own built-in role field (separate
   from group membership). Set `false` if you want admins to also need
   actual group membership.
4. Optional, not required for safety: this tool's own Workspace → Tools
   list entry may have a working Access Control / share option (native
   Tools have a real `AccessGrants` system wired up server-side,
   confirmed via `open_webui/models/tools.py` — unlike Direct Tool Server
   connections, see History). Scoping it to the `Operator` group there
   too costs nothing and hides it from others' tool pickers, but the
   actual authorization is the in-code group check regardless of that
   setting — never treat that UI control as the real gate.
5. Attach the tool to a Model, or leave it globally available — the code
   denies non-operators either way, so global availability just means
   non-operators can see it listed and get a clean refusal, not that
   they can use it.

Group membership is re-checked on **every call**, not cached — removing
someone from `Operator` takes effect on their very next tool call, no
Open WebUI restart or re-login required.

## Step 4 — Assign users

Default users → `Analyst` group. Add someone to `Operator` only against a
documented change request (Prompt 3 below) — this is an access-escalation
decision, not a routine one. Full admins get tuning access automatically
via `ALLOW_ADMIN_ROLE` (Step 3.3) regardless of group membership, unless
that valve is turned off.

## Defense in depth — now two independent layers, not one

The MCP server itself is still the authoritative boundary, unchanged from
before: `sigliere_mcp_server.py`'s `require_role`/`_mcp_auth` reject
`set_frequency`/`mcp_set_frequency` for any token whose mapped role isn't
`operator`, regardless of which caller presents it. Confirmed live
2026-08-08 (server was in dry-run mode for this specific test; the role
gate itself doesn't depend on dry-run state):

| Token role | `POST /set_frequency` | 
|---|---|
| analyst | **403** (role analyst lacks operator permission) |
| operator | **200** |

**As of 2026-08-11 there's a second, independent layer on top of that:**
the operator bearer token itself now lives only inside
`sigint_operator_tool.py`'s admin-only Valves — no Open WebUI user can
reach it directly the way they could with a shared connection, and the
tool's own code re-checks the calling user's group/role before ever
using that token. So a misconfiguration here (e.g. leaving
`ALLOW_ADMIN_ROLE` on when you didn't mean to) is still a real thing to
get right, but the blast radius of getting Open WebUI's *own* sharing
settings wrong — the failure mode this whole doc used to be about — is
gone, because there's no shared connection left to misconfigure.

## History: why this doc changed (read before reusing the old approach)

The original plan (Steps 2–3 through 2026-08-08) was to register the
operator endpoint as a Direct Tool Server connection and restrict it to
the `Operator` group via that connection's own Access Control setting —
the same sharing mechanism Models/Knowledge use. Checked live
2026-08-11, operator driving the browser, this agent with no login of
its own:

- No Access Control / share icon anywhere on the Tool Servers list row
  or its edit dialog — confirmed by direct inspection, not by source
  reading (the dialog only has `Type`/`Name`/`Description`/`URL`/`Auth`/
  `API Key`/`OpenAPI Spec`).
- Group `Permissions` has a `Direct Tool Servers` toggle, but it's
  all-or-nothing (can this group use ANY registered connection at all),
  not per-connection.
- Models can only attach the native Python `Tools`, not Direct Tool
  Server connections at all — confirmed by the tool picker only ever
  showing the four existing SIGINT tools, never an MCP connection.

Net effect: once a Direct Tool Server connection is registered globally,
any user with the (default-on) `Direct Tool Servers` permission could
enable and use it themselves — including one carrying an operator bearer
token — regardless of Open WebUI group membership. The
"SIGINT MCP (Operator)" connection was deleted for exactly this reason,
replaced by the native tool in Step 3. Full investigation trail:
`docs/mcp-validation-evidence.md`, 2026-08-11 entries.

**If you're tempted to scope a Direct Tool Server connection to a group
for anything else in the future: don't, on this Open WebUI version.** Use
the native-tool-with-code-check pattern instead.

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

(Realized as of 2026-08-11 via `openwebui-tools/sigint_operator_tool.py`'s
`list_sdr_nodes`/`set_sdr_frequency` methods plus the existing analyst
connection for the read-only three — not via a Direct Tool Server
connection scoped to an operator role/group, see History above.)

### Prompt 3: user assignment policy

Assign default users to analyst role unless there is an explicit operational requirement.
Only approved radio operators may be assigned to operator role.
Require a documented change request before operator role assignment.

### Prompt 4: token handling policy

Store analyst and operator bearer tokens separately.
Rotate operator tokens on schedule and after staffing changes.
Never paste operator tokens into shared channels or role descriptions.

`~/.config/sigliere/mcp.env` is already `0600` (owner-only). The "store
separately" intent is realized more strongly than originally planned: the
operator token isn't just in a separate *connection* from the analyst
token (the original plan) — as of 2026-08-11 it isn't in any
Open-WebUI-user-visible surface at all, only in
`sigint_operator_tool.py`'s admin-only Valves.
