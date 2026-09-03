from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from sigedge_client import SigedgeClient, SigedgeNode

ROLE_ORDER = {"analyst": 1, "operator": 2}


class TuneRequest(BaseModel):
    node_id: str
    frequency_hz: float = Field(..., ge=1_000, le=6_000_000_000)
    mode: str


class GatewayState:
    def __init__(self) -> None:
        path = Path(os.environ.get("SIGLIERE_SIGEDGE_NODES", "/app/config/nodes.json"))
        self.nodes = self._load_nodes(path)
        try:
            self.tokens: dict[str, str] = json.loads(
                os.environ.get("SIGLIERE_GATEWAY_TOKENS_JSON", "{}")
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError("SIGLIERE_GATEWAY_TOKENS_JSON must be valid JSON") from exc
        dry_run = os.environ.get("SIGLIERE_GATEWAY_DRY_RUN", "true").lower() == "true"
        self.client = SigedgeClient(dry_run=dry_run)

    @staticmethod
    def _load_nodes(path: Path) -> dict[str, SigedgeNode]:
        payload = json.loads(path.read_text())
        if payload.get("version") != 1:
            raise RuntimeError("unsupported SIGedge node contract version")
        nodes: dict[str, SigedgeNode] = {}
        for item in payload.get("nodes", []):
            node = SigedgeNode(
                node_id=item["node_id"],
                label=item.get("label", item["node_id"]),
                status_address=item["status_address"],
                min_hz=float(item["min_hz"]),
                max_hz=float(item["max_hz"]),
                modes=tuple(str(mode).lower() for mode in item["modes"]),
                control_enabled=bool(item.get("control_enabled", False)),
            )
            if node.node_id in nodes:
                raise RuntimeError(f"duplicate node_id: {node.node_id}")
            nodes[node.node_id] = node
        return nodes

    def authorize(self, token: str, minimum: str) -> str:
        role = self.tokens.get(token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid bearer token")
        if ROLE_ORDER.get(role, 0) < ROLE_ORDER[minimum]:
            raise HTTPException(status_code=403, detail=f"{minimum} role required")
        return role


state = GatewayState()
app = FastAPI(
    title="SIGliere SIGedge Gateway",
    version="1.0.0",
    description="Authenticated AI-tier access to SIGedge KA9Q multicast services.",
)


def bearer(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="bearer token required")
    return authorization.split(None, 1)[1]


def analyst(token: Annotated[str, Depends(bearer)]) -> str:
    return state.authorize(token, "analyst")


def operator(token: Annotated[str, Depends(bearer)]) -> str:
    return state.authorize(token, "operator")


def public_node(node: SigedgeNode) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "label": node.label,
        "status_address": node.status_address,
        "min_hz": node.min_hz,
        "max_hz": node.max_hz,
        "modes": list(node.modes),
        "control_enabled": node.control_enabled,
    }


@app.get("/healthz")
def healthz(_: Annotated[str, Depends(analyst)]) -> dict[str, Any]:
    return {
        "status": "ok",
        "dry_run": state.client.dry_run,
        "configured_nodes": len(state.nodes),
    }


@app.get("/nodes")
def nodes(_: Annotated[str, Depends(analyst)]) -> dict[str, Any]:
    return {"nodes": [public_node(node) for node in state.nodes.values()]}


@app.get("/status")
def all_status(_: Annotated[str, Depends(analyst)]) -> dict[str, Any]:
    results = []
    for node in state.nodes.values():
        try:
            results.append(state.client.status(node))
        except Exception as exc:
            results.append({
                "node_id": node.node_id,
                "reachable": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            })
    return {"nodes": results}


@app.get("/status/{node_id}")
def node_status(node_id: str, _: Annotated[str, Depends(analyst)]) -> dict[str, Any]:
    node = state.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node_id")
    try:
        return state.client.status(node)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/tune")
def tune(request: TuneRequest, _: Annotated[str, Depends(operator)]) -> dict[str, Any]:
    node = state.nodes.get(request.node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node_id")
    try:
        return state.client.tune(
            node, frequency_hz=request.frequency_hz, mode=request.mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("SIGLIERE_GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("SIGLIERE_GATEWAY_PORT", "8140")),
    )

