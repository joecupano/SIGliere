"""Bearer-token gate in front of the MCP app (pure ASGI, no dependencies)."""

import hmac
import json


class BearerAuth:
    """Reject any HTTP request without the exact bearer token, before MCP
    handling. Non-HTTP scopes (lifespan) pass through untouched."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError("BearerAuth requires a non-empty token")
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, rest = value.partition(b" ")
                if scheme.lower() == b"bearer":
                    supplied = rest.strip()
                break
        if not hmac.compare_digest(supplied, self._token):
            body = json.dumps({"error": "unauthorized"}).encode()
            await send({
                "type": "http.response.start", "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
