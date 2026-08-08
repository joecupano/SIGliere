# The DB→AI Query Path — How the Local LLM Queries Occupancy

**Status: WORKING.** The local LLM (via Open WebUI) can query the occupancy
database in natural language and answers from real data the RX-888 and HackRF captured.
This document records the working solution and why it is the way it is, since
getting here involved three approaches and several dead ends worth not
repeating.

## Current working paths

Two paths are now operational on this build:

1. **OpenAPI external-tool connection in Open WebUI** backed by
  `openapi-tools/sigint_openapi_server.py`.
2. **Native in-process Open WebUI Python tool** via
  `openwebui-tools/sigint_occupancy_tool.py`.

The OpenAPI path is the active UI-facing connection path when Open WebUI is
configured with Type=OpenAPI. The native tool path remains valid for
in-process workflows.

## Native in-process Open WebUI Python tool path

The path that works is a **native in-process Open WebUI tool**:
`openwebui-tools/sigint_occupancy_tool.py`. It defines a `Tools`
class with `query_occupancy` and `radiod_status`, type-hinted with Sphinx
docstrings the model reads, and queries the occupancy SQLite directly.

### Deploying it (the two things that matter)

1. **Mount the occupancy DB dir into the Open WebUI container.** The tool runs
   inside the container, so the DB must be visible there. In the Quadlet
   (`~/.config/containers/systemd/open-webui.container`), add a **plain
   read-write** bind mount of the whole `db/` directory:
   ```
   Volume=/home/<user>/sovereign-sigint/db:/data/sigint
   ```
   Then `systemctl --user daemon-reload && systemctl --user restart open-webui`.

   - Mount the **whole directory**, not just `occupancy.db` — WAL mode uses
     `-wal`/`-shm` sidecar files that must come along.
   - Use a **plain read-write** mount: NOT `:ro` (SQLite in WAL mode must
     touch the sidecars even to read, so `:ro` fails), and NOT `:U` (that
     would chown the host dir to the container's user and break the radiod
     producer's writes). The tool stays safe via a query-level guard (below).

2. **Install the tool in Open WebUI** — full step-by-step (including the
   model-registration step tools silently fail without) is in
   `docs/openwebui-setup-guide.md` ("Installing a Native Tool"). In brief:
   Workspace → Tools → create new → paste
   the file → Save. Confirm the `DB_PATH` valve is `/data/sigint/occupancy.db`
   (the default, matching the mount). Attach it to your model (Workspace →
   Models → model → Tools) and/or enable it per-chat via the tools icon.

### Why it's safe even with a read-write mount

The tool opens a normal SQLite connection (needed for WAL) but sets
`PRAGMA query_only=ON`, which makes SQLite reject any write on that
connection — verified: reads succeed, writes fail with "readonly database".
So it reads the live, continuously-written DB correctly without being able to
modify it. `busy_timeout` lets a read wait briefly if the producer holds the
write lock.

### Model note

Tool *calling* reliability depends on the model. In testing, the call fired
from a tool-capable local model with the tool attached and Function Calling =
Native; an explicit instruction ("Call query_occupancy now with low_hz … and
high_hz … and report the results") reliably triggered execution. Smaller
models may need the explicit phrasing; see Open WebUI's guidance that native
in-process tools are the most reliable tool path for local models.

## Other approaches and where they fit

### MCP server (planned, documented in the MCP design docs)
The MCP approach is documented in [MCP-server-design.md](MCP-server-design.md).
It remains a future integration path rather than a separate implementation
branch in this repository. Open WebUI's native MCP client has had compatibility
issues in the past, so the current working path stays the native Open WebUI
tool approach described above.

### OpenAPI tool server (active Open WebUI external-tool connection path)
`openapi-tools/sigint_openapi_server.py` is reachable and returns real data.
For Open WebUI OpenAPI connections, use browser-reachable URLs for both fields:

- URL: `http://<box-lan-ip>:8130`
- OpenAPI Spec URL: `http://<box-lan-ip>:8130/openapi.json`

Do not mix MCP endpoint URLs into an OpenAPI connection.

## Summary

| Approach | Status | Use when |
|----------|--------|----------|
| OpenAPI tool server | **WORKING** | Open WebUI Type=OpenAPI connections and other HTTP clients. |
| **Native Open WebUI tool** | **WORKING** | In-process Open WebUI workflows where native tool attachment is preferred. |
| MCP server | Parked (Open WebUI MCP client bug) | Other MCP clients (Claude/Goose) now; Open WebUI once its MCP client is fixed. |

The capture→DB→AI loop is closed: RF → RX-888 → radiod → occupancy producer →
occupancy DB → Open WebUI tool path (OpenAPI external or native in-process) →
local LLM answering in natural language, entirely on local hardware.
