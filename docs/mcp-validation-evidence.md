# MCP Validation Evidence

This log captures objective post-merge validation evidence for the MCP server path.

## 2026-08-05 Dry-Run Validation (Test Server)

- Timestamp (UTC): 2026-08-05T04:39:30Z
- Branch: main
- Commit: 4fc8715
- Validation script: scripts/phase6-mcp-server-validate.sh
- Container image: localhost/sigliere-mcp:latest
- Runtime mode: SIGLIERE_MCP_DRY_RUN=true

### Command

```bash
cd /home/baldrick/sigliere
bash scripts/phase6-mcp-server-validate.sh
```

### Results

- health endpoint: PASS
- node inventory: PASS (3 nodes: rx888-hf, hackrf-vhf-uhf, rtlsdr-v4)
- frequency routing: PASS (146.520 MHz routed to hackrf-vhf-uhf)
- operator action path: PASS (`set_frequency` returned dry-run success)
- overall validation: PASS

### Captured Output (summary)

```text
[mcp-validate] health: {"ok":true,"role":"analyst","node_count":3,"dry_run":true}
[mcp-validate] route: {"role":"analyst","frequency_hz":146520000.0,"node_id":"hackrf-vhf-uhf","radiod_instance":"hackrf-vhf-uhf"}
[mcp-validate] set_frequency: {"dry_run":true,"node_id":"hackrf-vhf-uhf","frequency_hz":146520000.0,"mode":"nfm","note":"Dry-run enabled; no radiod change was sent.","role":"operator"}
[mcp-validate] PASS
```

## Evidence Policy

- Add a new dated entry for each significant MCP change merged to main.
- Record branch, commit, runtime mode, and command used.
- Prefer dry-run evidence first; add a separate section for controlled live tests.
