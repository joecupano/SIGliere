"""
title: SIGedge Operator Control
author: SIGliere
description: Request SIGedge tuning through the authenticated local gateway.
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
        GATEWAY_OPERATOR_TOKEN: str = Field(
            default="",
            description="Operator token from ~/.config/sigliere/gateway.env.",
        )
        OPERATOR_GROUP_NAME: str = Field(default="Operator")
        ALLOW_ADMIN_ROLE: bool = Field(default=True)
        TIMEOUT_SEC: float = Field(default=10.0, ge=1.0, le=60.0)

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    async def _require_operator(self, user: dict) -> str | None:
        if not user or not user.get("id"):
            return "Error: calling user could not be determined; request refused."
        if self.valves.ALLOW_ADMIN_ROLE and user.get("role") == "admin":
            return None
        try:
            from open_webui.models.groups import Groups

            groups = await Groups.get_groups_by_member_id(user["id"])
        except Exception as exc:
            return f"Error checking Open WebUI group membership: {exc}"
        names = {group.name.strip().casefold() for group in groups}
        if self.valves.OPERATOR_GROUP_NAME.strip().casefold() not in names:
            return "Not authorized: Operator group membership is required."
        return None

    async def _call(self, method: str, path: str, **kwargs) -> str:
        if not self.valves.GATEWAY_OPERATOR_TOKEN:
            return "Error: GATEWAY_OPERATOR_TOKEN is not configured."
        url = f"{self.valves.GATEWAY_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SEC) as client:
                response = await client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self.valves.GATEWAY_OPERATOR_TOKEN}"
                    },
                    **kwargs,
                )
        except Exception as exc:
            return f"Error reaching SIGedge gateway: {exc.__class__.__name__}: {exc}"
        if response.status_code != 200:
            return f"SIGedge gateway returned {response.status_code}: {response.text}"
        return json.dumps(response.json(), indent=2)

    async def list_sigedge_nodes(self, __user__: dict = {}) -> str:
        """List SIGedge nodes available for authorized control."""
        denied = await self._require_operator(__user__)
        if denied:
            return denied
        return await self._call("GET", "/nodes")

    async def tune_sigedge(
        self,
        node_id: str,
        frequency_hz: float,
        mode: str,
        __user__: dict = {},
    ) -> str:
        """
        Request a SIGedge node channel at a frequency and mode. The gateway
        starts in dry-run mode; live control must be enabled separately.

        :param node_id: Logical SIGedge node ID from list_sigedge_nodes.
        :param frequency_hz: Requested frequency in Hz.
        :param mode: Mode allowed by the node contract.
        """
        denied = await self._require_operator(__user__)
        if denied:
            return denied
        return await self._call(
            "POST",
            "/tune",
            json={
                "node_id": node_id,
                "frequency_hz": frequency_hz,
                "mode": mode,
            },
        )

