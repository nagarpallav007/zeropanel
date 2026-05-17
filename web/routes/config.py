import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth import get_current_user
from web.config import BASE_DIR

router = APIRouter()

_NGINX_AVAIL    = Path("/etc/nginx/sites-available")
_PHP_BASE       = Path("/etc/php")
_WEB_EXEC_CONFIG = "/opt/panel/bin/web-exec-config"


def _find_php_version(domain: str) -> str | None:
    conf = _NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        return None
    m = re.search(r"php(\d+\.\d+)-fpm", conf.read_text())
    return m.group(1) if m else None


def _assert_site(username: str, site: str):
    if not (BASE_DIR / username / "sites" / site).exists():
        raise HTTPException(404, "Site not found")


@router.get("/config")
async def get_config(type: str, site: str, username: str = Depends(get_current_user)):
    _assert_site(username, site)

    if type == "nginx":
        path = _NGINX_AVAIL / f"{site}.conf"
        if not path.exists():
            raise HTTPException(404, "nginx config not found")
        return {"content": path.read_text(), "path": str(path)}

    if type == "phpfpm":
        ver = _find_php_version(site)
        if not ver:
            raise HTTPException(404, "Could not determine PHP version for this site")
        path = _PHP_BASE / ver / "fpm" / "pool.d" / f"{username}.conf"
        if not path.exists():
            raise HTTPException(404, "PHP-FPM pool config not found")
        return {"content": path.read_text(), "path": str(path), "php_version": ver}

    raise HTTPException(400, "type must be 'nginx' or 'phpfpm'")


class ConfigIn(BaseModel):
    type: str
    site: str
    content: str


@router.post("/config")
async def save_config(body: ConfigIn, username: str = Depends(get_current_user)):
    _assert_site(username, body.site)

    if body.type == "nginx":
        cmd = [_WEB_EXEC_CONFIG, "write-nginx-vhost", body.site]
    elif body.type == "phpfpm":
        ver = _find_php_version(body.site)
        if not ver:
            raise HTTPException(404, "Could not determine PHP version")
        cmd = [_WEB_EXEC_CONFIG, "write-phpfpm-pool", username, ver]
    else:
        raise HTTPException(400, "type must be 'nginx' or 'phpfpm'")

    result = subprocess.run(
        ["sudo", *cmd],
        input=body.content.encode(),
        capture_output=True,
    )
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace").strip()
        raise HTTPException(500, f"Config save failed: {err}")

    return {"ok": True}
