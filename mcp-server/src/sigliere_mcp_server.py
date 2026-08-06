#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from radiod_adapter import RadiodAdapter, RadiodNode

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None


ROLE_ORDER = {
    "analyst": 1,
    "operator": 2,
}


class RouteRequest(BaseModel):
    frequency_hz: float = Field(..., ge=1_000, le=6_000_000_000)


class TuneRequest(BaseModel):
    node_id: str
    frequency_hz: float = Field(..., ge=1_000, le=6_000_000_000)
    mode: str


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    kind: str
    radiod_instance: str
    host: str
    port: int
    status_address: str | None
    min_hz: float
    max_hz: float
    modes: list[str]
    boot_ssrc: int | None = None
    boot_mode: str | None = None


class ServerState:
    def __init__(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]
        default_nodes = self.repo_root / "mcp-server" / "config" / "nodes.json"
        cfg_path = Path(os.environ.get("SIGLIERE_MCP_NODES_JSON", str(default_nodes)))

        raw_tokens = os.environ.get("SIGLIERE_MCP_TOKENS_JSON", "{}")
        try:
            self.tokens: dict[str, str] = json.loads(raw_tokens)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SIGLIERE_MCP_TOKENS_JSON must be valid JSON") from exc

        self.nodes = self._load_nodes(cfg_path)
        dry_run = os.environ.get("SIGLIERE_MCP_DRY_RUN", "true").strip().lower() == "true"
        self.adapter = RadiodAdapter(dry_run=dry_run)

    def _load_nodes(self, path: Path) -> dict[str, NodeConfig]:
        if not path.exists():
            raise RuntimeError(f"nodes config not found at {path}")

        payload = json.loads(path.read_text())
        configs = {}
        for item in payload.get("nodes", []):
            cfg = NodeConfig(
                node_id=item["node_id"],
                kind=item["kind"],
                radiod_instance=item["radiod_instance"],
                host=item["host"],
                port=int(item["port"]),
                status_address=item.get("status_address"),
                min_hz=float(item["min_hz"]),
                max_hz=float(item["max_hz"]),
                modes=[str(m).lower() for m in item["modes"]],
                boot_ssrc=int(item["boot_ssrc"]) if item.get("boot_ssrc") is not None else None,
                boot_mode=item.get("boot_mode"),
            )
            configs[cfg.node_id] = cfg
        return configs

    def authz(self, token: str, min_role: str) -> str:
        role = self.tokens.get(token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid token")
        if ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 99):
            raise HTTPException(status_code=403, detail=f"role {role} lacks {min_role} permission")
        return role

    def route_frequency(self, frequency_hz: float) -> NodeConfig:
        for node in self.nodes.values():
            if node.min_hz <= frequency_hz <= node.max_hz:
                return node
        raise HTTPException(status_code=422, detail="no SDR node can cover requested frequency")

    def as_radiod_node(self, cfg: NodeConfig) -> RadiodNode:
        return RadiodNode(
            node_id=cfg.node_id,
            radiod_instance=cfg.radiod_instance,
            host=cfg.host,
            port=cfg.port,
            kind=cfg.kind,
            status_address=cfg.status_address,
            boot_ssrc=cfg.boot_ssrc,
            boot_mode=cfg.boot_mode,
        )


state = ServerState()
app = FastAPI(
    title="Sigliere MCP Security Gateway",
    version="0.1.0",
    description=(
        "Zero-trust role-gated control plane for radiod-backed SDR nodes. "
        "Use analyst role for read operations and operator role for tuning changes."
    ),
)


def _token_from_auth_header(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def require_role(min_role: str):
    def _dep(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> str:
        token = _token_from_auth_header(authorization)
        return state.authz(token, min_role=min_role)

    return _dep


@app.get("/healthz")
def healthz(role: str = Depends(require_role("analyst"))) -> dict[str, Any]:
    return {
        "ok": True,
        "role": role,
        "node_count": len(state.nodes),
        "dry_run": state.adapter.dry_run,
    }


@app.get("/nodes")
def list_nodes(role: str = Depends(require_role("analyst"))) -> dict[str, Any]:
    nodes = [
        {
            "node_id": n.node_id,
            "kind": n.kind,
            "radiod_instance": n.radiod_instance,
            "host": n.host,
            "port": n.port,
            "min_hz": n.min_hz,
            "max_hz": n.max_hz,
            "modes": n.modes,
            "boot_ssrc": n.boot_ssrc,
            "boot_mode": n.boot_mode,
        }
        for n in state.nodes.values()
    ]
    return {"role": role, "count": len(nodes), "nodes": nodes}


@app.post("/route_frequency")
def route_frequency(req: RouteRequest, role: str = Depends(require_role("analyst"))) -> dict[str, Any]:
    node = state.route_frequency(req.frequency_hz)
    return {
        "role": role,
        "frequency_hz": req.frequency_hz,
        "node_id": node.node_id,
        "radiod_instance": node.radiod_instance,
    }


@app.get("/radiod_status/{node_id}")
def get_radiod_status(node_id: str, role: str = Depends(require_role("analyst"))) -> dict[str, Any]:
    cfg = state.nodes.get(node_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="unknown node_id")
    out = state.adapter.service_state(state.as_radiod_node(cfg))
    out["role"] = role
    return out


@app.post("/set_frequency")
def set_frequency(req: TuneRequest, role: str = Depends(require_role("operator"))) -> dict[str, Any]:
    cfg = state.nodes.get(req.node_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="unknown node_id")

    if not (cfg.min_hz <= req.frequency_hz <= cfg.max_hz):
        raise HTTPException(
            status_code=422,
            detail=f"frequency_hz must be between {cfg.min_hz} and {cfg.max_hz} for {cfg.node_id}",
        )

    mode = req.mode.strip().lower()
    if mode not in cfg.modes:
        raise HTTPException(status_code=422, detail=f"mode must be one of {cfg.modes}")

    try:
        result = state.adapter.set_frequency(
            node=state.as_radiod_node(cfg),
            frequency_hz=req.frequency_hz,
            mode=mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result["role"] = role
    return result


if FastMCP is not None:
    mcp = FastMCP("sigliere-radiod-bridge")

    def _mcp_auth(token: str, required: str) -> None:
        state.authz(token=token, min_role=required)

    @mcp.tool()
    def mcp_list_nodes(token: str) -> dict[str, Any]:
        _mcp_auth(token, "analyst")
        return list_nodes(role="analyst")

    @mcp.tool()
    def mcp_route_frequency(token: str, frequency_hz: float) -> dict[str, Any]:
        _mcp_auth(token, "analyst")
        return route_frequency(RouteRequest(frequency_hz=frequency_hz), role="analyst")

    @mcp.tool()
    def mcp_radiod_status(token: str, node_id: str) -> dict[str, Any]:
        _mcp_auth(token, "analyst")
        return get_radiod_status(node_id=node_id, role="analyst")

    @mcp.tool()
    def mcp_set_frequency(token: str, node_id: str, frequency_hz: float, mode: str) -> dict[str, Any]:
        _mcp_auth(token, "operator")
        req = TuneRequest(node_id=node_id, frequency_hz=frequency_hz, mode=mode)
        return set_frequency(req=req, role="operator")


def main() -> None:
    transport = os.environ.get("SIGLIERE_MCP_TRANSPORT", "http").strip().lower()
    host = os.environ.get("SIGLIERE_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("SIGLIERE_MCP_PORT", "8140"))

    if transport == "stdio":
        if FastMCP is None:
            raise RuntimeError("mcp package is not importable; cannot run stdio transport")
        mcp.run()
        return

    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
