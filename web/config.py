import os
from pathlib import Path

JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
DB_PATH: Path = Path(os.environ.get("DB_PATH", "/opt/panel/data/webpanel.db"))
BASE_DIR: Path = Path("/srv/clients")
TOKEN_EXPIRY_HOURS: int = 8
MAX_FILE_READ_BYTES: int = 1 * 1024 * 1024  # 1 MB

# Commands allowed in the browser terminal (mirrors restricted-shell whitelist)
ALLOWED_CMDS = frozenset([
    "git", "composer", "npm", "node",
    "ls", "pwd", "mkdir", "cp", "mv", "rm",
    "unzip", "tar", "cat", "head", "tail", "tee",
])
