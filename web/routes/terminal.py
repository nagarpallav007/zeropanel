import asyncio
import json
import re
import shlex

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.auth import decode_token
from web.config import ALLOWED_CMDS, BASE_DIR
from web.db import log_action

router = APIRouter()

_WEB_EXEC = "/opt/panel/bin/web-exec"
_PHP_RE = re.compile(r"^php[0-9.]*$")


def _allowed(cmd: str) -> bool:
    return cmd in ALLOWED_CMDS or bool(_PHP_RE.match(cmd))


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket, site: str = ""):
    token = websocket.cookies.get("access_token")
    username = decode_token(token) if token else None
    if not username:
        await websocket.close(code=4001, reason="Unauthenticated")
        return

    site_dir = BASE_DIR / username / "sites" / site / "public_html"
    if not site_dir.exists():
        await websocket.close(code=4003, reason="Site not found")
        return

    await websocket.accept()
    process: asyncio.subprocess.Process | None = None

    async def send(obj: dict) -> None:
        await websocket.send_text(json.dumps(obj))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue

            cmd_str = msg.get("cmd", "").strip()
            if not cmd_str:
                continue

            try:
                tokens = shlex.split(cmd_str)
            except ValueError as exc:
                await send({"type": "output", "line": f"parse error: {exc}"})
                await send({"type": "exit", "code": 1})
                continue

            if not tokens or not _allowed(tokens[0]):
                label = tokens[0] if tokens else ""
                await send({"type": "output", "line": f"command not allowed: {label}"})
                await send({"type": "exit", "code": 127})
                continue

            await log_action(username, "terminal_cmd", cmd_str)

            process = await asyncio.create_subprocess_exec(
                "sudo", "-u", username, _WEB_EXEC, *tokens,
                cwd=str(site_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            async for raw_line in process.stdout:
                await send({"type": "output", "line": raw_line.decode(errors="replace").rstrip("\n")})

            await process.wait()
            await send({"type": "exit", "code": process.returncode})
            process = None

    except WebSocketDisconnect:
        pass
    finally:
        if process is not None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
