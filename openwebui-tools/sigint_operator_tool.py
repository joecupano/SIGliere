"""
title: SIGINT Operator Control
author: Sigliere
description: Change SDR tuning (frequency/mode) via the MCP control plane.
    Restricted to members of the Open WebUI 'operator' group, or full
    admins (ALLOW_ADMIN_ROLE valve) -- enforced in code on every call, not
    by Open WebUI's connection-sharing settings. Native in-process Open
    WebUI tool, same pattern as the other SIGINT tools
    (occupancy/kismet/sigid/whisper).
version: 1.0.0
license: AGPL-3.0
"""
#
# WHY THIS EXISTS, AND WHY IT'S SHAPED THIS WAY (read before editing):
#   The original plan was to register the MCP server's operator endpoint as
#   an external "Direct Tool Server" connection (Type=OpenAPI, Bearer
#   token) and restrict it to the `operator` Open WebUI group via that
#   connection's own sharing settings -- the same mechanism used for
#   Models/Knowledge. Checked live against this host's running Open WebUI
#   0.11.0 (2026-08-11) and confirmed that mechanism does NOT exist for
#   Direct Tool Server connections in this build:
#     - No Access Control / share icon anywhere on the Tool Servers list
#       row or its edit dialog (Type/Name/Description/URL/Auth/API
#       Key/OpenAPI Spec only -- nothing else).
#     - Group Permissions has a "Direct Tool Servers" toggle, but it's
#       all-or-nothing (can this group use ANY registered connection),
#       not per-connection.
#     - Models can only attach the native Python Tools (this kind of file),
#       not Direct Tool Server connections at all.
#   Net effect: once a Direct Tool Server connection is registered
#   globally, any user with the "Direct Tool Servers" permission (on by
#   default) can enable and use it themselves -- including one carrying an
#   operator bearer token. The "SIGINT MCP (Operator)" connection was
#   deleted from Admin Panel -> Settings -> Tools -> Tool Servers for
#   exactly this reason; do not re-add it without solving this problem
#   again first.
#
#   This tool is the replacement: instead of a shared connection carrying
#   a token any permitted user could invoke, it's a native in-process tool
#   that holds the operator token privately (Valves, admin-only -- see
#   below) and checks the CALLING USER's actual Open WebUI group
#   membership, live, on every single call, using Open WebUI's own
#   internal Groups model (verified against this host's installed
#   /app/backend/open_webui/models/groups.py: `Groups =
#   GroupTable()` is a module-level singleton;
#   `await Groups.get_groups_by_member_id(user_id)` returns
#   `list[GroupModel]`, each with a plain `.name` string). Confirmed live
#   that Open WebUI passes tool methods a `__user__` dict (via
#   `utils/tools.py`'s `get_async_tool_function_and_apply_extra_params`)
#   sourced from `user.model_dump()` -- not something a chat user can
#   forge from the chat itself.
#
# REQUIRED SETUP (do this before using):
#   1. Workspace -> Tools -> "SIGINT Operator Control" -> Valves (gear
#      icon): set MCP_OPERATOR_TOKEN to the operator token from
#      ~/.config/sigliere/mcp.env's SIGLIERE_MCP_TOKENS_JSON. Every method
#      below fails closed (refuses) if this is empty -- it does not fall
#      back to guessing or to a weaker check.
#   2. Confirm the Open WebUI group named exactly "operator" exists
#      (Admin Panel -> Users -> Groups) with the right members. If you
#      name it something else, update the OPERATOR_GROUP_NAME valve to
#      match -- it's a plain string compare, no magic lookup.
#   3. Optional, defense-in-depth, not load-bearing: this tool's own
#      Workspace -> Tools list entry may have a working Access Control /
#      share option (native Tools have a proper AccessGrants system wired
#      up server-side, unlike Direct Tool Server connections -- confirmed
#      in `open_webui/models/tools.py`, not independently confirmed live
#      in the UI by this agent). If present, scoping it to the `operator`
#      group there too costs nothing and hides the tool from others in
#      their tool picker -- but the actual authorization is the group
#      check in `_require_operator()` below regardless of that setting.
#   4. MCP_BASE_URL default (http://host.containers.internal:8140) is
#      confirmed reachable from inside this container as of 2026-08-11 --
#      open-webui.container is bridge-networked (PublishPort=...), NOT
#      host-networked like sigliere-mcp.container is, so 127.0.0.1 here
#      would NOT reach it. Only change this if your MCP server's
#      host/port differs from the default.
#
# SAFETY MODEL:
#   - Group membership is re-checked on EVERY call, not cached -- removing
#     someone from the `operator` group takes effect on their very next
#     tool call, no Open WebUI restart or re-login required.
#   - The operator bearer token lives only in this tool's admin-only
#     Valves, never in a shared connection any permitted user could
#     self-enable.
#   - set_sdr_frequency actually changes live hardware if the MCP server
#     is not in dry-run mode (SIGLIERE_MCP_DRY_RUN in
#     ~/.config/sigliere/mcp.env) -- this tool does not know or care
#     whether dry-run is on; that's the MCP server's own separate gate.

import json
from typing import Optional

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        MCP_BASE_URL: str = Field(
            default="http://host.containers.internal:8140",
            description="Base URL of the sigliere-mcp server AS SEEN FROM "
            "INSIDE the Open WebUI container. See the header comment for "
            "why this differs from 127.0.0.1.",
        )
        MCP_OPERATOR_TOKEN: str = Field(
            default="",
            description="Operator-role bearer token, from "
            "~/.config/sigliere/mcp.env's SIGLIERE_MCP_TOKENS_JSON. "
            "REQUIRED -- every method fails closed if this is empty. Only "
            "visible/editable to this tool's creator or a full admin (Open "
            "WebUI's own valve-access rule), never to a regular user.",
        )
        OPERATOR_GROUP_NAME: str = Field(
            default="Operator",
            description="Open WebUI group name whose members may call "
            "set_sdr_frequency (case-insensitive match). Default matches "
            "this repo's group as actually created ('Operator', capital "
            "O) -- confirmed live against this host's database "
            "2026-08-11; change if yours differs. Re-checked fresh on "
            "every call.",
        )
        ALLOW_ADMIN_ROLE: bool = Field(
            default=True,
            description="If true, any Open WebUI account with role=admin "
            "may use set_sdr_frequency even if not personally a member of "
            "the operator group. Checked against Open WebUI's own "
            "built-in role field, separate from group membership. Set "
            "false to require actual operator-group membership even for "
            "admins.",
        )
        TIMEOUT_SEC: float = Field(
            default=10.0, description="HTTP timeout (seconds) for calls to the MCP server."
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    # -- internal: the actual authorization gate ----------------------------
    async def _require_operator(self, __user__: dict) -> Optional[str]:
        """Returns None if the calling user is currently a member of the
        operator group OR is a full Open WebUI admin (see ALLOW_ADMIN_ROLE);
        otherwise an error string the caller should return directly instead
        of proceeding. Never caches a prior result."""
        if not __user__ or not __user__.get("id"):
            return "Error: could not determine the calling user; refusing to proceed."
        if self.valves.ALLOW_ADMIN_ROLE and __user__.get("role") == "admin":
            # Deliberately bypasses the group lookup entirely for admins --
            # not just "counts as a member", a genuinely separate check
            # against __user__["role"] (Open WebUI's own built-in role,
            # confirmed live via UserModel.role -- 'admin'/'user'/'pending'),
            # so this can't be defeated by anything group-membership-related.
            return None
        try:
            from open_webui.models.groups import Groups
        except ImportError as e:
            return (
                f"Error: could not import Open WebUI's Groups model "
                f"({e.__class__.__name__}: {e}) -- this tool only runs "
                f"in-process inside Open WebUI, not standalone."
            )
        try:
            groups = await Groups.get_groups_by_member_id(__user__["id"])
        except Exception as e:
            return f"Error checking group membership: {e.__class__.__name__}: {e}"
        names = {g.name.strip().lower() for g in groups}
        if self.valves.OPERATOR_GROUP_NAME.strip().lower() not in names:
            who = __user__.get("name") or __user__["id"]
            return (
                f"Not authorized: '{who}' is not a member of the "
                f"'{self.valves.OPERATOR_GROUP_NAME}' group. No change was made."
            )
        return None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.valves.MCP_OPERATOR_TOKEN}"}

    async def _call(self, method: str, path: str, **kwargs) -> str:
        if not self.valves.MCP_OPERATOR_TOKEN:
            return "Error: MCP_OPERATOR_TOKEN valve is not set. Configure it in this tool's Valves first."
        url = f"{self.valves.MCP_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SEC) as client:
                r = await client.request(method, url, headers=self._headers(), **kwargs)
        except Exception as e:
            return f"Error reaching MCP server at {url}: {e.__class__.__name__}: {e}"
        if r.status_code != 200:
            return f"MCP server returned {r.status_code}: {r.text}"
        return json.dumps(r.json(), indent=2)

    # -- tool 1: list nodes ---------------------------------------------------
    async def list_sdr_nodes(self, __user__: dict = {}) -> str:
        """
        List the SDR nodes available for tuning through the MCP control
        plane -- node_id, kind, frequency range, and supported modes. Use
        this before set_sdr_frequency to see valid node_id/mode values.
        Restricted to the operator group.

        :return: JSON list of nodes, or an authorization/error message.
        """
        denied = await self._require_operator(__user__)
        if denied:
            return denied
        return await self._call("GET", "/nodes")

    # -- tool 2: set frequency -------------------------------------------------
    async def set_sdr_frequency(
        self,
        node_id: str,
        frequency_hz: float,
        mode: str,
        __user__: dict = {},
    ) -> str:
        """
        Retune a given SDR node to a specific frequency and demodulation
        mode via the MCP control plane. THIS ACTUALLY CHANGES LIVE
        HARDWARE unless the MCP server is currently in dry-run mode.
        Restricted to the operator group -- checked fresh on every call.
        Call list_sdr_nodes first to confirm a valid node_id and an
        allowed mode for it.

        :param node_id: Target node id, e.g. "rx888-hf" or "hackrf-vhf-uhf" (see list_sdr_nodes).
        :param frequency_hz: Target frequency in Hz.
        :param mode: Demodulation mode -- must be one of that node's allowed modes (see list_sdr_nodes).
        :return: JSON result from the MCP server, or an authorization/error message.
        """
        denied = await self._require_operator(__user__)
        if denied:
            return denied
        body = {"node_id": node_id, "frequency_hz": frequency_hz, "mode": mode}
        return await self._call("POST", "/set_frequency", json=body)
