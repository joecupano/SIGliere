"""Read-only SQLite access shared by the mirror-database tools."""

import sqlite3
from pathlib import Path


def connect_ro(db_path) -> sqlite3.Connection:
    """Open db_path read-only with dict-style rows. These tools never write;
    the host-side producer's brief write locks are waited out via the connect
    timeout."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn
