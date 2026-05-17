import subprocess
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File as FastAPIFile, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from web.auth import get_current_user
from web.config import BASE_DIR, MAX_FILE_READ_BYTES
from web.db import log_action

router = APIRouter()

# Commands that write/modify files — routed through web-exec as the site user
_WEB_EXEC = "/opt/panel/bin/web-exec"


def _safe(username: str, rel: str) -> Path:
    """Resolve a user-supplied relative path and assert it stays inside the user's base dir."""
    base = (BASE_DIR / username).resolve()
    target = (base / rel.lstrip("/")).resolve()
    if str(target) != str(base) and not str(target).startswith(str(base) + "/"):
        raise HTTPException(403, "Path outside user directory")
    return target


def _sudo_exec(username: str, *cmd: str, stdin: bytes | None = None) -> tuple[int, str]:
    result = subprocess.run(
        ["sudo", "-u", username, _WEB_EXEC, *cmd],
        input=stdin,
        capture_output=True,
    )
    return result.returncode, (result.stderr or b"").decode(errors="replace").strip()


@router.get("/files")
async def list_dir(path: str = "", username: str = Depends(get_current_user)):
    target = _safe(username, path)
    if not target.exists():
        raise HTTPException(404, "Not found")
    if not target.is_dir():
        raise HTTPException(400, "Not a directory")
    entries = []
    try:
        for item in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            try:
                st = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "file" if item.is_file() else "dir",
                    "size": st.st_size if item.is_file() else None,
                    "mtime": int(st.st_mtime),
                })
            except OSError:
                pass
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {"path": path, "entries": entries}


@router.get("/files/read")
async def read_file(path: str, username: str = Depends(get_current_user)):
    target = _safe(username, path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    if target.stat().st_size > MAX_FILE_READ_BYTES:
        raise HTTPException(413, "File too large for editor (> 1 MB)")
    try:
        async with aiofiles.open(target, "r", errors="replace") as f:
            content = await f.read()
    except PermissionError:
        raise HTTPException(403, "Permission denied reading file")
    return {"path": path, "content": content}


class WriteIn(BaseModel):
    path: str
    content: str


@router.post("/files/write")
async def write_file(body: WriteIn, username: str = Depends(get_current_user)):
    target = _safe(username, body.path)
    code, err = _sudo_exec(username, "tee", str(target), stdin=body.content.encode())
    if code != 0:
        raise HTTPException(500, f"Write failed: {err}")
    await log_action(username, "file_write", body.path)
    return {"ok": True}


@router.post("/files/upload")
async def upload_file(
    path: str,
    file: UploadFile = FastAPIFile(...),
    username: str = Depends(get_current_user),
):
    dest_dir = _safe(username, path)
    if not dest_dir.is_dir():
        raise HTTPException(400, "Upload destination must be a directory")
    fname = Path(file.filename or "upload").name
    if not fname or fname in (".", ".."):
        raise HTTPException(400, "Invalid filename")
    dest = _safe(username, str(Path(path.lstrip("/")) / fname))  # re-validate full path
    content = await file.read()
    code, err = _sudo_exec(username, "tee", str(dest), stdin=content)
    if code != 0:
        raise HTTPException(500, f"Upload failed: {err}")
    rel = str(dest.relative_to((BASE_DIR / username).resolve()))
    await log_action(username, "file_upload", rel)
    return {"ok": True, "path": rel}


@router.get("/files/download")
async def download_file(path: str, username: str = Depends(get_current_user)):
    target = _safe(username, path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(target), filename=target.name)


class MkdirIn(BaseModel):
    path: str


@router.post("/files/mkdir")
async def make_dir(body: MkdirIn, username: str = Depends(get_current_user)):
    target = _safe(username, body.path)
    code, err = _sudo_exec(username, "mkdir", "-p", str(target))
    if code != 0:
        raise HTTPException(500, f"mkdir failed: {err}")
    return {"ok": True}


class RenameIn(BaseModel):
    from_path: str
    to_path: str


@router.post("/files/rename")
async def rename_file(body: RenameIn, username: str = Depends(get_current_user)):
    src  = _safe(username, body.from_path)
    dest = _safe(username, body.to_path)
    code, err = _sudo_exec(username, "mv", str(src), str(dest))
    if code != 0:
        raise HTTPException(500, f"Rename failed: {err}")
    await log_action(username, "file_rename", f"{body.from_path} → {body.to_path}")
    return {"ok": True}


@router.delete("/files")
async def delete_file(path: str, username: str = Depends(get_current_user)):
    target = _safe(username, path)
    if not target.is_file():
        raise HTTPException(400, "Can only delete files, not directories")
    code, err = _sudo_exec(username, "rm", str(target))
    if code != 0:
        raise HTTPException(500, f"Delete failed: {err}")
    await log_action(username, "file_delete", path)
    return {"ok": True}
