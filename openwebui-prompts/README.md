# Open WebUI prompts

Use [SIGINT-analyst.system-prompt.md](SIGINT-analyst.system-prompt.md) as the
system prompt for the model that has the native SIGedge tools attached.

The prompt encodes the tiered ownership boundary and prevents the model from
inventing local hardware or collection access. Install the tools and configure
their tokens first; see the [Open WebUI setup guide](../docs/openwebui-setup.md).

Use [SIGINT-analyst-mcp.system-prompt.md](SIGINT-analyst-mcp.system-prompt.md)
instead for a model that gets the Kismet, occupancy, SigID, and MAC tools from
the optional MCP server ([design](../docs/mcp-server-design.md)). It drops the
per-tool Kismet paragraph, because the MCP tool descriptions carry that
guidance. Do not mix the two prompts with the wrong tool set.

