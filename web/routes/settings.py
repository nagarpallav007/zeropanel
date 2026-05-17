import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.config import BASE_DIR

router = APIRouter()

_NGINX_AVAIL = Path("/etc/nginx/sites-available")
_PHP_BASE    = Path("/etc/php")


def _parse_nginx_limit(domain: str) -> str:
    conf = _NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        return "unknown"
    m = re.search(r"client_max_body_size\s+(\S+);", conf.read_text())
    return m.group(1) if m else "not set"


def _find_php_version(domain: str) -> str | None:
    conf = _NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        return None
    m = re.search(r"php(\d+\.\d+)-fpm", conf.read_text())
    return m.group(1) if m else None


def _parse_pool_value(username: str, version: str, key: str) -> str:
    pool = _PHP_BASE / version / "fpm" / "pool.d" / f"{username}.conf"
    if not pool.exists():
        return "not set"
    m = re.search(rf"php_admin_value\[{re.escape(key)}\]\s*=\s*(\S+)", pool.read_text())
    return m.group(1) if m else "not set"


@router.get("/settings")
async def get_settings(site: str, username: str = Depends(get_current_user)):
    site_path = BASE_DIR / username / "sites" / site
    if not site_path.exists():
        raise HTTPException(404, "Site not found")

    nginx_limit = _parse_nginx_limit(site)
    php_ver     = _find_php_version(site)
    php_upload  = _parse_pool_value(username, php_ver, "upload_max_filesize") if php_ver else "unknown"
    php_post    = _parse_pool_value(username, php_ver, "post_max_size")       if php_ver else "unknown"

    return {
        "nginx_limit": nginx_limit,
        "php_upload":  php_upload,
        "php_post":    php_post,
        "php_version": php_ver or "unknown",
        "cli_command": f"sudo panel set-upload-limit {username} {site} <size>",
    }
