"""Shared, UI-agnostic logic behind SIGliere's data-source tools.

Everything here is pure Python on the standard library: no Open WebUI, no
pydantic, no MCP. The Open WebUI tools in openwebui-tools/src/ are thin
wrappers that add docstrings, valves, and error text on top of these
functions; scripts/build-owui-tools.py inlines this package into the
self-contained single-file tools that are pasted into Workspace -> Tools.

Because modules are inlined into one flat namespace, public names are unique
across the package (kismet_*/occupancy_*/mac_*/sigid_* prefixes where a short
name would collide).
"""
