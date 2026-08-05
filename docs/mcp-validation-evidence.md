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

## 2026-08-05 Controlled Non-Dry-Run Action Test

- Timestamp (UTC): 2026-08-05T05:05:04Z
- Branch: main
- Commit: 29d2d18
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `hackrf-vhf-uhf` at 146.520 MHz

### Command Pattern

- Started ephemeral MCP container with dry-run disabled and test role tokens.
- Called `/healthz`, `/route_frequency`, `/radiod_status/hackrf-vhf-uhf`, and `/set_frequency`.

### Results

- health endpoint: PASS
- route_frequency: PASS
- radiod_status: DEGRADED (`active: error:FileNotFoundError`, socket unreachable)
- set_frequency: FAIL (HTTP 500)

### Failure Detail

```text
HTTP=500
{"detail":"radiod command failed: module 'ka9q' has no attribute 'Client'"}
```

### Interpretation

- The live action path is blocked by adapter/library API mismatch in `mcp-server/src/radiod_adapter.py`.
- Current adapter assumes `ka9q.Client`, but installed `ka9q-python` version does not expose that symbol.

### Required Remediation Before Production Action Mode

1. Update `mcp-server/src/radiod_adapter.py` to match the actual `ka9q-python` API used on this host.
2. Re-run this controlled non-dry-run test and require HTTP 200 on `set_frequency`.
3. Keep dry-run mode as default until live action path passes.

## 2026-08-05 Controlled Non-Dry-Run Action Retest (Remediated)

- Timestamp (UTC): 2026-08-05T05:09:06Z
- Branch: main
- Commit under test: e61b86d
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `hackrf-vhf-uhf` at 146.520 MHz

### Remediation Applied

1. Replaced legacy `ka9q.Client` usage with `ka9q.RadiodControl` flow in `mcp-server/src/radiod_adapter.py`.
2. Added explicit `status_address` values to `mcp-server/config/nodes.json` so the container does not depend on `avahi-browse` discovery for this host.
3. Plumbed optional `status_address` through server config in `mcp-server/src/sigliere_mcp_server.py`.

### Results

- health endpoint: PASS
- set_frequency: PASS (HTTP 200)
- response: includes `status: "applied"` and resolved `status_address`

### Captured Output (summary)

```text
HTTP=200
{"dry_run":false,"node_id":"hackrf-vhf-uhf","frequency_hz":146520000.0,"mode":"nfm","preset":"nfm","status_address":"239.172.80.224","status":"applied","role":"operator"}
```

### Residual Notes

- Container logs reported `TTL=0` warnings for multicast stream distribution; this did not block control-path success.

## 2026-08-05 Controlled Non-Dry-Run RX-888 Action Test

- Timestamp (UTC): 2026-08-05T05:10:42Z
- Branch: main
- Commit under test: cfb5d84
- Runtime mode: SIGLIERE_MCP_DRY_RUN=false
- Scope: single operator `set_frequency` call for `rx888-hf` at 7.100 MHz (`usb`)

### Command Pattern

- Started ephemeral MCP container with dry-run disabled and test role tokens.
- Called `/route_frequency` for `7100000` and then `/set_frequency` for `rx888-hf`.

### Results

- route_frequency: PASS (`7100000` mapped to `rx888-hf`)
- set_frequency: PASS (HTTP 200)

### Captured Output (summary)

```text
HTTP=200
{"dry_run":false,"node_id":"rx888-hf","frequency_hz":7100000.0,"mode":"usb","preset":"usb","status_address":"239.95.191.236","status":"applied","role":"operator"}
```

### Residual Notes

- Container logs reported `TTL=0` warnings for multicast stream distribution; this did not block control-path success.

## Evidence Policy

- Add a new dated entry for each significant MCP change merged to main.
- Record branch, commit, runtime mode, and command used.
- Prefer dry-run evidence first; add a separate section for controlled live tests.

## 2026-08-05 Open WebUI Integration Readiness Check

- Timestamp (UTC): 2026-08-05T04:41:27Z
- Branch: main
- Commit: cafd650
- Command: `bash scripts/openwebui-mcp-command.sh`

### Result

- status: BLOCKED (configuration prerequisite missing)
- blocker: `/home/baldrick/.config/sigliere/mcp.env` not found

### Remediation

1. Create the host env file from `mcp-server/mcp.env.example`.
2. Fill in real token values for `SIGLIERE_MCP_TOKENS_JSON` and `SIGLIERE_OPERATOR_TOKEN`.
3. Re-run `bash scripts/openwebui-mcp-command.sh` and capture generated URL/header output.
4. Paste output into Open WebUI MCP Tool settings and validate tool loading.

## 2026-08-05 Open WebUI Settings Generation (Unblocked)

- Timestamp (UTC): 2026-08-05T04:41:54Z
- Branch: main
- Commit: fb70162
- Local setup: created `/home/baldrick/.config/sigliere/mcp.env` from `mcp-server/mcp.env.example`
- Command: `bash scripts/openwebui-mcp-command.sh`

### Result

- status: PASS (settings generated)
- output:

```text
Name: Sigliere MCP
Type: Streamable HTTP
URL: http://0.0.0.0:8140
Headers:
	Authorization: Bearer operator-token
```

### Follow-up Required

- Replace placeholder token values in `/home/baldrick/.config/sigliere/mcp.env` before production use.

## 2026-08-05 Dry-Run Validation After Secret-Key Durability Change

- Timestamp (UTC): 2026-08-05T05:04:03Z
- Branch: main
- Commit: 02a0728
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
