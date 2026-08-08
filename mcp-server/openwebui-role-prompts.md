# Open WebUI Role Provisioning — analyst / operator

**Status as of 2026-08-08:** the token infrastructure below is live and
confirmed working (see `docs/mcp-validation-evidence.md`'s 2026-08-08
entry). The Open WebUI-side steps (registering the two connections,
creating the two groups, scoping access) have **not** been applied to the
running instance — that part requires logging into Open WebUI's Admin
Panel, which needs the operator's credentials. No agent working on this
repo has (or should have) that login; see Guardrail 7 in the project
handoff doc. Everything below is ready to paste; only the manual UI clicks
remain, by the operator.

## Step 0 — Generate the two connection blocks

```bash
bash scripts/openwebui-mcp-command.sh
```

prints one paste-ready block for **analyst** and one for **operator**
(Name / Type / URL / Headers), each carrying its own real bearer token
pulled live from `~/.config/sigliere/mcp.env`'s `SIGLIERE_MCP_TOKENS_JSON`
— there are no placeholders left in that file as of this session. Pass
`analyst` or `operator` as an argument to print just one block.

## Step 1 — Register both as separate connections in Open WebUI

**Admin Panel → Settings → Tools/Connections** (exact label not
independently confirmed against a live login on this build of 0.11.x —
verify against what your instance actually shows) → add a connection for
each of the two Step 0 blocks, Type = MCP / Streamable HTTP. You should end
up with two distinct tool entries, e.g. "Sigliere MCP (analyst)" and
"Sigliere MCP (operator)" — do **not** merge them into one connection with
one token; the whole point is that they carry different tokens.

## Step 2 — Create the two groups

**Admin Panel → Users → Groups → Create:**
- `analyst` — default group; read-only MCP access
  (`mcp_list_nodes`, `mcp_route_frequency`, `mcp_radiod_status`).
- `operator` — read + tuning access (adds `mcp_set_frequency` /
  `POST /set_frequency`). Approved radio operators only.

## Step 3 — Scope each connection to its group

Restrict the "Sigliere MCP (operator)" connection's visibility to the
`operator` group only (Open WebUI's per-connection/tool access control —
Private + group selection, or the group's own Permissions tab, depending
on version). Leave "Sigliere MCP (analyst)" available to everyone/default.

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
analyst could see a connection meant for operators), not a safety hole —
the server refuses the tuning call either way.

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
