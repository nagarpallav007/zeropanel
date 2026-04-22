import re
from pathlib import Path

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from config import BASE, DEFAULT_PHP, NGINX_AVAIL, NGINX_ENABLED
from utils.nginx import build_config
from utils.shell import _log, run, sudo_chown_r, sudo_mkdir, sudo_write
from utils.validate import validate_domain, validate_php, validate_username

console = Console()


def _php_socket(version: str) -> Path:
    return Path(f"/run/php/php{version}-fpm.sock")


def add_site(
    username: str,
    domain: str,
    php: str = typer.Option(DEFAULT_PHP, help="PHP-FPM version"),
):
    """Provision a new site for a user: directories, nginx config, index.php."""
    validate_username(username)
    validate_domain(domain)
    validate_php(php)

    sock = _php_socket(php)
    if not sock.exists():
        print(f"[red]PHP {php} socket not found: {sock}[/red]")
        raise typer.Exit(1)

    root = BASE / username / "sites" / domain / "public_html"
    logs = BASE / username / "sites" / domain / "logs"

    sudo_mkdir(root)
    sudo_mkdir(logs)
    sudo_chown_r(BASE / username, username)

    index = root / "index.php"
    if not index.exists():
        sudo_write(index, "<?php phpinfo();\n", owner=username)

    conf = build_config(domain, str(root), str(logs), str(sock))
    conf_path = NGINX_AVAIL / f"{domain}.conf"
    sudo_write(conf_path, conf)

    link = NGINX_ENABLED / f"{domain}.conf"
    if not link.exists():
        run(["sudo", "ln", "-s", str(conf_path), str(link)])

    run(["sudo", "nginx", "-t"])
    run(["sudo", "systemctl", "reload", "nginx"])

    _log("add-site", username=username, domain=domain, php=php)
    print(f"[green]Site ready:[/green] {domain}")


def delete_site(
    username: str,
    domain: str,
    purge: bool = typer.Option(False, "--purge", help="Also delete site files"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a site's nginx config, optionally deleting all site files."""
    validate_username(username)
    validate_domain(domain)

    if not yes:
        msg = f"Delete site '{domain}'"
        if purge:
            msg += " and purge all files"
        typer.confirm(f"{msg}?", abort=True)

    for path in [NGINX_ENABLED / f"{domain}.conf", NGINX_AVAIL / f"{domain}.conf"]:
        run(["sudo", "rm", "-f", str(path)], check=False)

    if purge:
        site_path = BASE / username / "sites" / domain
        run(["sudo", "rm", "-rf", str(site_path)], check=False)

    run(["sudo", "systemctl", "reload", "nginx"])

    _log("delete-site", username=username, domain=domain, purge=purge)
    print(f"[green]Site deleted:[/green] {domain}")


def list_sites(username: str = typer.Argument(None, help="Filter by username")):
    """List all sites with PHP version, enabled state, and SSL status."""
    if not BASE.exists():
        print("[yellow]No clients directory found.[/yellow]")
        return

    users = (
        [BASE / username] if username else sorted(BASE.iterdir())
    )

    table = Table(title="Sites", show_header=True, header_style="bold cyan")
    table.add_column("Domain")
    table.add_column("User")
    table.add_column("PHP")
    table.add_column("Enabled")
    table.add_column("SSL")

    for user_dir in users:
        if not user_dir.is_dir():
            continue
        sites_dir = user_dir / "sites"
        if not sites_dir.exists():
            continue
        for site_dir in sorted(sites_dir.iterdir()):
            domain = site_dir.name
            conf_path = NGINX_AVAIL / f"{domain}.conf"
            php_ver = "?"
            if conf_path.exists():
                m = re.search(r"php(\d+\.\d+)-fpm\.sock", conf_path.read_text())
                php_ver = m.group(1) if m else "?"

            enabled = (
                "[green]yes[/green]"
                if (NGINX_ENABLED / f"{domain}.conf").exists()
                else "[red]no[/red]"
            )
            cert = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
            ssl = "[green]yes[/green]" if cert.exists() else "[dim]no[/dim]"

            table.add_row(domain, user_dir.name, php_ver, enabled, ssl)

    console.print(table)


def disable_site(domain: str):
    """Disable a site by removing its nginx symlink."""
    validate_domain(domain)

    link = NGINX_ENABLED / f"{domain}.conf"
    if not link.exists():
        print(f"[yellow]{domain} is already disabled[/yellow]")
        raise typer.Exit()

    run(["sudo", "rm", str(link)])
    run(["sudo", "systemctl", "reload", "nginx"])

    _log("disable-site", domain=domain)
    print(f"[yellow]Disabled:[/yellow] {domain}")


def enable_site(domain: str):
    """Re-enable a site by creating its nginx symlink."""
    validate_domain(domain)

    conf = NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        print(f"[red]No config found for {domain}[/red]")
        raise typer.Exit(1)

    link = NGINX_ENABLED / f"{domain}.conf"
    if link.exists():
        print(f"[yellow]{domain} is already enabled[/yellow]")
        raise typer.Exit()

    run(["sudo", "ln", "-s", str(conf), str(link)])
    run(["sudo", "systemctl", "reload", "nginx"])

    _log("enable-site", domain=domain)
    print(f"[green]Enabled:[/green] {domain}")


def set_php(domain: str, version: str):
    """Switch the PHP-FPM version for a site."""
    validate_domain(domain)
    validate_php(version)

    conf = NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        print("[red]Site config not found[/red]")
        raise typer.Exit(1)

    sock = _php_socket(version)
    if not sock.exists():
        print(f"[red]PHP {version} socket not found: {sock}[/red]")
        raise typer.Exit(1)

    text = conf.read_text()
    text = re.sub(r"php\d+\.\d+-fpm\.sock", f"php{version}-fpm.sock", text)
    sudo_write(conf, text)

    run(["sudo", "nginx", "-t"])
    run(["sudo", "systemctl", "reload", "nginx"])

    _log("set-php", domain=domain, version=version)
    print(f"[green]{domain} now uses PHP {version}[/green]")
