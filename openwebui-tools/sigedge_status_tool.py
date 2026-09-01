"""
title: SIGedge Status
author: Sigliere
description: Read configured SIGedge nodes and their live KA9Q multicast status.
version: 1.0.0
license: AGPL-3.0
"""

import json

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        GATEWAY_BASE_URL: str = Field(
            default="http://127.0.0.1:8180/gateway",
            description="Caddy's loopback-only route to the SIGedge gateway.",
        )
        GATEWAY_ANALYST_TOKEN: str = Field(
            default="",
            description="Analyst token from ~/.config/sigliere/gateway.env.",
        )
        TIMEOUT_SEC: float = Field(default=10.0, ge=1.0, le=60.0)

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    async def _get(self, path: str) -> str:
        if not self.valves.GATEWAY_ANALYST_TOKEN:
            return "Error: GATEWAY_ANALYST_TOKEN is not configured."
        url = f"{self.valves.GATEWAY_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SEC) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.valves.GATEWAY_ANALYST_TOKEN}"
                    },
                )
        except Exception as exc:
            return f"Error reaching SIGedge gateway: {exc.__class__.__name__}: {exc}"
        if response.status_code != 200:
            return f"SIGedge gateway returned {response.status_code}: {response.text}"
        return json.dumps(response.json(), indent=2)

    async def list_sigedge_nodes(self) -> str:
        """
        List SIGedge collection nodes, their frequency ranges, supported
        modes, multicast status addresses, and whether control is enabled.
        """
        return await self._get("/nodes")

    async def sigedge_status(self, node_id: str = "") -> str:
        """
        Read live KA9Q multicast status. Omit node_id to check every node.

        :param node_id: Optional logical SIGedge node ID from list_sigedge_nodes.
        """
        path = f"/status/{node_id}" if node_id else "/status"
        return await self._get(path)

