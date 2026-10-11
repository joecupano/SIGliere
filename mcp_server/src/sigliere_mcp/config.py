"""Environment-driven configuration. Defaults match the paths the container
sees (the same read-only mount targets Open WebUI's native tools use)."""

import os
from dataclasses import dataclass, field

MIN_TOKEN_LENGTH = 32


class ConfigError(RuntimeError):
    pass


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8150
    kismet_db: str = "/data/kismet-bridge-ref/kismet_bridge.db"
    occupancy_db: str = "/data/occupancy-ref/occupancy.db"
    sigid_dir: str = "/data/sigid-ref/metadata"
    mac_db: str = "/data/mac-vendors-ref/mac-vendors.json"
    # DNS-rebinding protection: Host headers Caddy forwards on loopback.
    allowed_hosts: tuple = (
        "127.0.0.1:8150", "localhost:8150", "127.0.0.1:8180", "localhost:8180",
    )

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        token = env.get("SIGLIERE_MCP_TOKEN", "")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(
                f"SIGLIERE_MCP_TOKEN must be set to at least {MIN_TOKEN_LENGTH} "
                "characters (see scripts/install-sigliere-mcp.sh)"
            )
        defaults = cls(token=token)
        host = env.get("SIGLIERE_MCP_HOST", defaults.host)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ConfigError(
                f"SIGLIERE_MCP_HOST={host!r}: the MCP server must bind loopback only"
            )
        return cls(
            token=token,
            host=host,
            port=int(env.get("SIGLIERE_MCP_PORT", defaults.port)),
            kismet_db=env.get("KISMET_BRIDGE_DB_PATH", defaults.kismet_db),
            occupancy_db=env.get("OCCUPANCY_DB_PATH", defaults.occupancy_db),
            sigid_dir=env.get("SIGID_METADATA_DIR", defaults.sigid_dir),
            mac_db=env.get("MAC_VENDOR_DB_PATH", defaults.mac_db),
            allowed_hosts=tuple(_csv(env["SIGLIERE_MCP_ALLOWED_HOSTS"]))
            if env.get("SIGLIERE_MCP_ALLOWED_HOSTS") else defaults.allowed_hosts,
        )
