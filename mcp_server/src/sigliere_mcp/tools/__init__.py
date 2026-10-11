"""Tool modules. Each exposes register(mcp, cfg) and holds only thin wrappers:
open the data read-only, call sigliere_core, return compact JSON text."""

import json

from mcp.server.fastmcp.exceptions import ToolError

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


def dumps(obj) -> str:
    """Compact JSON: fewer tokens in the model's context than indent=2."""
    return json.dumps(obj, separators=(",", ":"))


def read_error(what: str, where: str, exc: Exception) -> ToolError:
    """Failures are protocol errors (isError), not prose the model might
    mistake for data."""
    return ToolError(f"Error reading {what} at '{where}': {exc.__class__.__name__}: {exc}")
