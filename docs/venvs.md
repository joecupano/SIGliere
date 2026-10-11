# Python environments

Optional host-side Python functions use capability-specific environments:

| Domain | Path | Requirements |
|---|---|---|
| AI ingest | `~/.local/share/sigliere/venvs/ai-ingest` | `ai-ingest/requirements.txt` |
| Reference mirrors | `~/.local/share/sigliere/venvs/reference` | `reference/requirements.txt` |
| Occupancy | `~/.local/share/sigliere/venvs/occupancy` | `occupancy/requirements.txt` |
| Kismet bridge | `~/.local/share/sigliere/venvs/kismet-bridge` | `kismet_bridge/requirements.txt` |

The SIGedge gateway and the MCP server (`mcp_server/`) are
containerized and installs `gateway/requirements.txt`
inside its image. No DSP or collection-processing environment exists here.

