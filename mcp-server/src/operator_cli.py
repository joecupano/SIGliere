#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests


def _base_url() -> str:
    host = os.environ.get("SIGLIERE_MCP_HOST", "127.0.0.1")
    port = os.environ.get("SIGLIERE_MCP_PORT", "8140")
    return f"http://{host}:{port}"


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("SIGLIERE_OPERATOR_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SIGLIERE_OPERATOR_TOKEN is required")
    return {"Authorization": f"Bearer {token}"}


def _req(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    resp = requests.request(method=method, url=url, json=payload, headers=_auth_headers(), timeout=15)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "body": resp.text}

    if resp.status_code >= 400:
        raise RuntimeError(f"request failed {resp.status_code}: {data}")
    return data


def cmd_nodes() -> int:
    out = _req("GET", "/nodes")
    print(out)
    return 0


def cmd_status(node_id: str) -> int:
    out = _req("GET", f"/radiod_status/{node_id}")
    print(out)
    return 0


def cmd_route(frequency_hz: float) -> int:
    out = _req("POST", "/route_frequency", {"frequency_hz": frequency_hz})
    print(out)
    return 0


def cmd_tune(node_id: str, frequency_hz: float, mode: str) -> int:
    out = _req(
        "POST",
        "/set_frequency",
        {
            "node_id": node_id,
            "frequency_hz": frequency_hz,
            "mode": mode,
        },
    )
    print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sigliere MCP operator CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("nodes", help="List configured SDR nodes")

    st = sub.add_parser("status", help="Get radiod status for a node")
    st.add_argument("node_id")

    ro = sub.add_parser("route", help="Route a frequency to the matching node")
    ro.add_argument("frequency_hz", type=float)

    tu = sub.add_parser("tune", help="Set node frequency/mode")
    tu.add_argument("node_id")
    tu.add_argument("frequency_hz", type=float)
    tu.add_argument("mode")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "nodes":
            return cmd_nodes()
        if args.command == "status":
            return cmd_status(args.node_id)
        if args.command == "route":
            return cmd_route(args.frequency_hz)
        if args.command == "tune":
            return cmd_tune(args.node_id, args.frequency_hz, args.mode)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
