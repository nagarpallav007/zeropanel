from collections import defaultdict
from time import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from web.auth import TOKEN_EXPIRY_HOURS, create_token, get_current_user, pam_authenticate
from web.config import BASE_DIR
from web.db import log_action

router = APIRouter()

_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 5
_RATE_WINDOW = 60  # seconds


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response, request: Request):
    ip = request.client.host or ""
    now = time()
    recent = [t for t in _attempts[ip] if now - t < _RATE_WINDOW]
    if len(recent) >= _RATE_LIMIT:
        raise HTTPException(429, "Too many login attempts — wait 60 seconds")
    _attempts[ip] = recent

    if not pam_authenticate(body.username, body.password):
        _attempts[ip].append(now)
        raise HTTPException(401, "Invalid credentials")

    token = create_token(body.username)
    response.set_cookie(
        "access_token", token,
        httponly=True, samesite="lax", max_age=TOKEN_EXPIRY_HOURS * 3600,
    )
    await log_action(body.username, "login", ip=ip)
    return {"username": body.username}


@router.post("/logout")
async def logout(response: Response, username: str = Depends(get_current_user)):
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me")
async def me(username: str = Depends(get_current_user)):
    sites_dir = BASE_DIR / username / "sites"
    sites = sorted(d.name for d in sites_dir.iterdir() if d.is_dir()) if sites_dir.exists() else []
    return {"username": username, "sites": sites}
