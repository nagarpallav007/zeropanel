import re
import secrets
import subprocess
import tempfile
from pathlib import Path

import typer
from rich import print

from utils.deps import _dpkg_installed, apt_update
from utils.nginx import set_limit
from utils.shell import run, sudo_write

_VENV_PIP  = Path("/opt/panel/venv/bin/pip")
_WEB_EXEC  = Path("/opt/panel/bin/web-exec")
_WEB_ENV   = Path("/opt/panel/.web.env")
_WEB_DATA  = Path("/opt/panel/data")
_WEB_DB    = Path("/opt/panel/data/webpanel.db")
_SUDOERS   = Path("/etc/sudoers.d/zeropanel-web")
_SYSTEMD   = Path("/etc/systemd/system/zeropanel-web.service")
_NGINX_AVAIL = Path("/etc/nginx/sites-available/zeropanel-web.conf")
_NGINX_LINK  = Path("/etc/nginx/sites-enabled/zeropanel-web.conf")

_WEB_PKGS = [
    "fastapi", "uvicorn[standard]", "python-pam",
    "python-jose[cryptography]", "aiofiles", "python-multipart", "aiosqlite",
]

_SYSTEMD_UNIT = """\
[Unit]
Description=zeropanel web interface
After=network.target nginx.service

[Service]
Type=simple
User=panel-web
Group=panel-web
WorkingDirectory=/opt/panel
EnvironmentFile=/opt/panel/.web.env
ExecStart=/opt/panel/venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

_SUDOERS_RULE = "panel-web ALL=(ALL:ALL) NOPASSWD: /opt/panel/bin/web-exec\n"


def _nginx_vhost(domain: str) -> str:
    return f"""\
server {{
    listen 80;
    server_name {domain};

    client_max_body_size 1G;

    location / {{
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
    }}
}}
"""


def set_panel_limit(
    size: str = typer.Argument("1G", help="Upload size limit e.g. 64M, 256M, 1G"),
):
    """Set client_max_body_size in the zeropanel nginx vhost (survives certbot rewrites)."""
    if not re.match(r"^\d+(K|M|G)$", size, re.IGNORECASE):
        print(f"[red]Invalid size: '{size}'. Use e.g. 64M, 256M, 1G[/red]")
        raise typer.Exit(1)
    size = size.upper()
    if not _NGINX_AVAIL.exists():
        print("[red]zeropanel nginx vhost not found — run panel activate-web first.[/red]")
        raise typer.Exit(1)
    set_limit(_NGINX_AVAIL, size)
    run(["sudo", "nginx", "-t"])
    run(["sudo", "nginx", "-s", "reload"])
    print(f"[green]Panel upload limit set to {size}[/green]")


def activate_web(
    domain: str = typer.Option(..., prompt="Domain or IP to serve the web panel on"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing configuration"),
):
    """Install and start the zeropanel browser-based file manager and terminal."""

    if _SYSTEMD.exists() and not force:
        typer.confirm("zeropanel-web is already configured. Overwrite?", abort=True)

    # ── 1. Install Python packages ───────────────────────────────────────────
    print("[bold]Step 1/8[/bold] Installing Python packages…")
    if not _VENV_PIP.exists():
        print("[red]venv not found at /opt/panel/venv — run the panel install steps first.[/red]")
        raise typer.Exit(1)

    existing = subprocess.run(
        [str(_VENV_PIP), "freeze"], capture_output=True, text=True
    ).stdout.lower()
    to_install = [p for p in _WEB_PKGS if p.split("[")[0].lower() not in existing]
    if to_install:
        run([str(_VENV_PIP), "install", "-q", *to_install])
    print("  [green]✓[/green] packages ready")

    # ── 2. Create panel-web system user ──────────────────────────────────────
    print("[bold]Step 2/8[/bold] Creating panel-web system user…")
    user_exists = subprocess.run(["id", "panel-web"], capture_output=True).returncode == 0
    if not user_exists:
        run(["sudo", "useradd", "--system", "--no-create-home",
             "--shell", "/usr/sbin/nologin", "panel-web"])
    # Must be in shadow group to read /etc/shadow for PAM authentication
    run(["sudo", "usermod", "-aG", "shadow", "panel-web"])
    print("  [green]✓[/green] panel-web user ready")

    # ── 3. Set permissions on bin/web-exec + write PAM service file ─────────
    print("[bold]Step 3/8[/bold] Securing web-exec wrapper and PAM service…")
    if not _WEB_EXEC.exists():
        print(f"[red]{_WEB_EXEC} not found — ensure the panel repo is complete.[/red]")
        raise typer.Exit(1)
    run(["sudo", "chmod", "755", str(_WEB_EXEC)])
    run(["sudo", "chown", "root:root", str(_WEB_EXEC)])
    # Custom PAM service: authenticates all system users regardless of shell,
    # so SFTP-only users (nologin) can log in alongside dev-tier users.
    pam_service = "auth    required   pam_unix.so\naccount required   pam_permit.so\n"
    sudo_write(Path("/etc/pam.d/zeropanel-web"), pam_service)
    print("  [green]✓[/green] web-exec secured, PAM service written")

    # ── 4. Write sudoers rule ────────────────────────────────────────────────
    print("[bold]Step 4/8[/bold] Configuring sudoers…")
    with tempfile.NamedTemporaryFile("w", suffix=".sudoers", delete=False) as tf:
        tf.write(_SUDOERS_RULE)
        tmp = tf.name
    result = subprocess.run(["visudo", "-c", "-f", tmp], capture_output=True)
    if result.returncode != 0:
        print("[red]sudoers syntax check failed — aborting.[/red]")
        raise typer.Exit(1)
    run(["sudo", "cp", tmp, str(_SUDOERS)])
    run(["sudo", "chmod", "440", str(_SUDOERS)])
    print("  [green]✓[/green] sudoers rule installed")

    # ── 5. Generate .web.env ─────────────────────────────────────────────────
    print("[bold]Step 5/8[/bold] Generating secrets…")
    jwt_secret = secrets.token_hex(32)
    env_content = f"JWT_SECRET={jwt_secret}\nDB_PATH={_WEB_DB}\n"
    sudo_write(_WEB_ENV, env_content)
    run(["sudo", "chown", "root:panel-web", str(_WEB_ENV)])
    run(["sudo", "chmod", "640", str(_WEB_ENV)])
    print("  [green]✓[/green] .web.env written")

    # ── 6. Init SQLite DB ────────────────────────────────────────────────────
    print("[bold]Step 6/8[/bold] Initialising database…")
    # SQLite needs write access to the containing directory (WAL/journal files)
    run(["sudo", "mkdir", "-p", str(_WEB_DATA)])
    run(["sudo", "chown", "panel-web:panel-web", str(_WEB_DATA)])
    run(["sudo", "chmod", "750", str(_WEB_DATA)])
    run(["sudo", "touch", str(_WEB_DB)])
    run(["sudo", "chown", "panel-web:panel-web", str(_WEB_DB)])
    run(["sudo", "chmod", "660", str(_WEB_DB)])
    print("  [green]✓[/green] database ready")

    # ── 7. Write systemd unit ────────────────────────────────────────────────
    print("[bold]Step 7/8[/bold] Installing systemd service…")
    sudo_write(_SYSTEMD, _SYSTEMD_UNIT)
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "enable", "--now", "zeropanel-web"])
    print("  [green]✓[/green] zeropanel-web service started")

    # ── 8. Configure nginx ───────────────────────────────────────────────────
    print("[bold]Step 8/8[/bold] Configuring nginx…")
    sudo_write(_NGINX_AVAIL, _nginx_vhost(domain))
    if not _NGINX_LINK.exists():
        run(["sudo", "ln", "-s", str(_NGINX_AVAIL), str(_NGINX_LINK)])
    run(["sudo", "nginx", "-t"])
    run(["sudo", "nginx", "-s", "reload"])
    print("  [green]✓[/green] nginx configured")

    print(f"""
[green bold]zeropanel web panel is live.[/green bold]

  URL   : [bold]http://{domain}[/bold]
  Login : your system username and password

Run [bold]sudo panel issue-ssl {domain} --no-www[/bold] to add HTTPS.
""")
