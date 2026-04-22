import re
from pathlib import Path

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from config import BASE, DEFAULT_PHP, NGINX_AVAIL, NGINX_ENABLED
from utils.nginx import build_config
from utils.phpfpm import ensure_pool, per_user_socket, pools_for_user, remove_pool
from utils.shell import _log, run, sudo_chown_r, sudo_mkdir, sudo_write
from utils.validate import validate_domain, validate_php, validate_username

console = Console()


def _php_installed(version: str) -> bool:
    return Path(f"/etc/php/{version}/fpm/pool.d/").exists()


def _find_user_for_domain(domain: str) -> str | None:
    if not BASE.exists():
        return None
    for user_dir in BASE.iterdir():
        if (user_dir / "sites" / domain).exists():
            return user_dir.name
    return None


def _get_site_php(domain: str) -> str | None:
    """Read PHP version from the nginx config for a domain."""
    conf = NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        return None
    m = re.search(r"php(\d+\.\d+)-fpm", conf.read_text())
    return m.group(1) if m else None


def _cleanup_pool_if_unused(username: str, version: str):
    """Remove the per-user PHP-FPM pool if no remaining sites for this user use it."""
    sites_dir = BASE / username / "sites"
    if not sites_dir.exists():
        remove_pool(username, version)
        return
    socket_marker = f"php{version}-fpm-{username}.sock"
    for site_dir in sites_dir.iterdir():
        conf = NGINX_AVAIL / f"{site_dir.name}.conf"
        if conf.exists() and socket_marker in conf.read_text():
            return  # another site still uses this pool
    remove_pool(username, version)


def add_site(
    username: str,
    domain: str,
    php: str = typer.Option(DEFAULT_PHP, help="PHP-FPM version"),
):
    """Provision a new site: directories, per-user PHP-FPM pool, nginx vhost, index.php."""
    validate_username(username)
    validate_domain(domain)
    validate_php(php)

    if not _php_installed(php):
        print(f"[red]PHP {php}-fpm is not installed (pool dir missing)[/red]")
        raise typer.Exit(1)

    root = BASE / username / "sites" / domain / "public_html"
    logs = BASE / username / "sites" / domain / "logs"

    sudo_mkdir(root)
    sudo_mkdir(logs)
    # Chown only the site subdir — top-level user dir stays root:root for ChrootDirectory
    sudo_chown_r(BASE / username / "sites" / domain, username)

    index = root / "index.php"
    if not index.exists():
        sudo_write(index, "<?php phpinfo();\n", owner=username)

    # Write per-user pool (idempotent) and reload php-fpm
    ensure_pool(username, php)
    sock = per_user_socket(username, php)

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

    # Read PHP version before removing the config
    php_ver = _get_site_php(domain)

    for path in [NGINX_ENABLED / f"{domain}.conf", NGINX_AVAIL / f"{domain}.conf"]:
        run(["sudo", "rm", "-f", str(path)], check=False)

    if purge:
        site_path = BASE / username / "sites" / domain
        run(["sudo", "rm", "-rf", str(site_path)], check=False)

    run(["sudo", "systemctl", "reload", "nginx"])

    # Remove pool if no remaining sites for this user use this PHP version
    if php_ver:
        _cleanup_pool_if_unused(username, php_ver)

    _log("delete-site", username=username, domain=domain, purge=purge)
    print(f"[green]Site deleted:[/green] {domain}")


def list_sites(username: str = typer.Argument(None, help="Filter by username")):
    """List all sites with PHP version, enabled state, and SSL status."""
    if not BASE.exists():
        print("[yellow]No clients directory found.[/yellow]")
        return

    users = [BASE / username] if username else sorted(BASE.iterdir())

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
                text = conf_path.read_text()
                # Try per-user socket format first, fall back to global
                m = re.search(r"php(\d+\.\d+)-fpm", text)
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

    if not _php_installed(version):
        print(f"[red]PHP {version}-fpm is not installed[/red]")
        raise typer.Exit(1)

    username = _find_user_for_domain(domain)
    if not username:
        print(f"[red]Cannot find owner for domain {domain}[/red]")
        raise typer.Exit(1)

    old_version = _get_site_php(domain)

    ensure_pool(username, version)
    new_sock = per_user_socket(username, version)

    text = conf.read_text()
    text = re.sub(
        r"php\d+\.\d+-fpm-\w+\.sock|php\d+\.\d+-fpm\.sock",
        str(new_sock).split("/")[-1],
        text,
    )
    sudo_write(conf, text)

    run(["sudo", "nginx", "-t"])
    run(["sudo", "systemctl", "reload", "nginx"])

    if old_version and old_version != version:
        _cleanup_pool_if_unused(username, old_version)

    _log("set-php", domain=domain, version=version)
    print(f"[green]{domain} now uses PHP {version}[/green]")
