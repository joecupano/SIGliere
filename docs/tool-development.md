# Developing the native tools

Four of the Open WebUI tools (Kismet bridge, occupancy, SigID, MAC vendor)
are built from shared logic rather than hand-maintained as single files. The
same `sigliere_core` functions also back the MCP server (`mcp_server/`), which
is now the recommended way to serve these tools; the generated single-file
tools are kept as a fallback for one release (see
[mcp-server-design.md](mcp-server-design.md)).

```text
sigliere_core/            UI-agnostic query/parse logic. Standard library only.
openwebui-tools/src/      Thin wrappers: LLM-facing docstrings, valves, error text.
openwebui-tools/*.py      GENERATED, self-contained tools. This is what you paste
                          into Workspace -> Tools. Do not edit by hand.
scripts/build-owui-tools.py   Inlines sigliere_core into each wrapper.
```

Open WebUI runs tools inside its container with no repo checkout, so a tool
cannot import `sigliere_core`. The build step inlines exactly the core modules
each wrapper imports, producing the same single-file, paste-in tool as before.
Installation instructions are unchanged.

## Changing a tool

1. Edit the logic in `sigliere_core/` or the wrapper in `openwebui-tools/src/`.
2. Rebuild: `python3 scripts/build-owui-tools.py`
3. Test: `python3 -m unittest discover -s tests`
4. Commit the source **and** the regenerated `openwebui-tools/*.py`.

`tests/test_owui_tools.py` fails if a generated file is stale
(`scripts/build-owui-tools.py --check` does the same from a shell or CI).

Core functions return Python data and never read valves or format strings;
wrappers own the LLM-facing wording. Public core names are unique across the
package (`kismet_*`, `mac_*`, `sigid_*` prefixes where needed) because modules
are inlined into one flat namespace.

`sigedge_status_tool.py`, `sigint_operator_tool.py`, and `sigint_whisper_tool.py`
are unchanged hand-written single files. The operator tool in particular stays
native so its live group-membership check is unaffected.

## Testing inside Open WebUI's environment

pydantic is only present in the Open WebUI image, so the wrapper-behavior
tests skip on a bare host. Run them where the tools actually run:

```bash
podman run --rm --network none -v "$PWD":/r:ro -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python ghcr.io/open-webui/open-webui:v0.12.0 \
  -m unittest discover -s /r/tests -p test_owui_tools.py
```
