import os
import subprocess
from pathlib import Path

import typer
from rich import print

from utils.deps import _dpkg_installed, apt_update
from utils.shell import run, sudo_write

PMA_CONF   = Path("/etc/nginx/sites-available/phpmyadmin.conf")
PMA_LINK   = Path("/etc/nginx/sites-enabled/phpmyadmin.conf")
PMA_HTPASS = Path("/etc/nginx/.pma_pass")


def _system_php_sock(version: str = "") -> str | None:
    php_base = Path("/etc/php")
    if not php_base.exists():
        return None
    if version:
        if (php_base / version / "fpm" / "pool.d").exists():
            return f"/run/php/php{version}-fpm.sock"
        return None
    versions = sorted(
        d.name for d in php_base.iterdir()
        if d.is_dir() and (d / "fpm" / "pool.d").exists()
    )
    if not versions:
        return None
    return f"/run/php/php{versions[-1]}-fpm.sock"


def _build_pma_nginx(server_name: str, php_sock: str) -> str:
    return f"""server {{
    listen 80;
    server_name {server_name};

    root /usr/share/phpmyadmin;
    index index.php;

    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.pma_pass;

    location / {{
        try_files $uri $uri/ =404;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{php_sock};
    }}

    location ~ /\\.ht {{
        deny all;
    }}
}}
"""


def install_phpmyadmin(
    domain: str = typer.Option(..., prompt="Domain or IP to serve phpMyAdmin on"),
    auth_user: str = typer.Option("admin", "--auth-user", prompt="HTTP basic auth username"),
    auth_pass: str = typer.Option(
        ..., "--auth-pass",
        prompt="HTTP basic auth password",
        hide_input=True,
        confirmation_prompt=True,
    ),
    php: str = typer.Option("", "--php", help="PHP version for FPM socket (auto-detected if omitted)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing phpMyAdmin configuration"),
):
    """Install and configure phpMyAdmin with nginx and HTTP basic auth."""
    sock = _system_php_sock(php)
    if not sock:
        version_hint = f" (version {php})" if php else ""
        print(f"[red]No PHP-FPM installation found{version_hint}. Install PHP-FPM first.[/red]")
        raise typer.Exit(1)

    if PMA_CONF.exists() and not force:
        typer.confirm("phpMyAdmin nginx config already exists. Overwrite?", abort=True)

    # Pre-seed debconf to suppress apt interactive prompts
    debconf_seeds = (
        "phpmyadmin phpmyadmin/reconfigure-webserver multiselect none\n"
        "phpmyadmin phpmyadmin/dbconfig-install boolean false\n"
    )
    subprocess.run(["sudo", "debconf-set-selections"], input=debconf_seeds, text=True, check=True)

    pkgs_needed = [p for p in ["phpmyadmin", "apache2-utils"] if not _dpkg_installed(p)]
    if pkgs_needed:
        print(f"[bold]Installing:[/bold] {', '.join(pkgs_needed)}")
        apt_update()
        subprocess.run(
            ["sudo", "-E", "apt-get", "install", "-y", "-qq", "--no-install-recommends", *pkgs_needed],
            check=True,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )

    # Write htpasswd — password piped via stdin so it never appears on the command line
    subprocess.run(
        ["sudo", "htpasswd", "-ci", str(PMA_HTPASS), auth_user],
        input=auth_pass + "\n",
        text=True,
        check=True,
    )

    sudo_write(PMA_CONF, _build_pma_nginx(domain, sock))

    if not PMA_LINK.exists():
        run(["sudo", "ln", "-s", str(PMA_CONF), str(PMA_LINK)])

    run(["sudo", "nginx", "-t"])
    run(["sudo", "nginx", "-s", "reload"])

    print(f"\n[green bold]phpMyAdmin ready.[/green bold]")
    print(f"  URL      : [bold]http://{domain}[/bold]")
    print(f"  Auth user: [bold]{auth_user}[/bold]")
    print(f"  PHP sock : [bold]{sock}[/bold]")
    print("\nLog in with your database credentials (from [bold]panel create-db[/bold]).")
