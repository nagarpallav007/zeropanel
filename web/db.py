import aiosqlite
from web.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT    NOT NULL,
    action   TEXT    NOT NULL,
    detail   TEXT    DEFAULT '',
    ip       TEXT    DEFAULT '',
    ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_SCHEMA)
        await db.commit()


async def log_action(username: str, action: str, detail: str = "", ip: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_log (username, action, detail, ip) VALUES (?, ?, ?, ?)",
            (username, action, detail, ip),
        )
        await db.commit()
