import re
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from config import BASE, DEFAULT_PHP, NGINX_AVAIL, NGINX_ENABLED
from utils.nginx import build_config, build_reverse_proxy_config, build_static_config
from utils.phpfpm import ensure_pool, per_user_socket, remove_pool
from utils.shell import _log, run, sudo_chown_r, sudo_mkdir, sudo_write
from utils.systemd import (
    build_node_service,
    build_python_asgi_service,
    build_python_wsgi_service,
    install_service,
    python_socket,
    remove_service,
    service_path,
)
from utils.validate import validate_domain, validate_php, validate_username

console = Console()

SITE_TYPES = ("php", "node", "python-wsgi", "python-asgi", "static")


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
    conf = NGINX_AVAIL / f"{domain}.conf"
    if not conf.exists():
        return None
    m = re.search(r"php(\d+\.\d+)-fpm", conf.read_text())
    return m.group(1) if m else None


def _read_site_type(username: str, domain: str) -> str:
    try:
        return (BASE / username / "sites" / domain / ".sitetype").read_text().strip()
    except OSError:
        return "php"


def _write_site_type(username: str, domain: str, site_type: str):
    sudo_write(BASE / username / "sites" / domain / ".sitetype", site_type + "\n")


def _cleanup_pool_if_unused(username: str, version: str):
    sites_dir = BASE / username / "sites"
    if not sites_dir.exists():
        remove_pool(username, version)
        return
    marker = f"php{version}-fpm-{username}.sock"
    for site_dir in sites_dir.iterdir():
        conf = NGINX_AVAIL / f"{site_dir.name}.conf"
        if conf.exists() and marker in conf.read_text():
            return
    remove_pool(username, version)


def add_site(
    username: str,
    domain: str,
    type: str = typer.Option("php", "--type", "-t", help=f"Site type: {', '.join(SITE_TYPES)}"),
    php: str = typer.Option(DEFAULT_PHP, "--php", help="PHP version (php type only)"),
    port: Optional[int] = typer.Option(None, "--port", help="App port — required for node"),
    app: Optional[str] = typer.Option(None, "--app", help="WSGI/ASGI app entry point, e.g. myapp:application"),
    entry: str = typer.Option("server.js", "--entry", help="Node.js entry file"),
):
    """Provision a new site. --type: php (default), node, python-wsgi, python-asgi, static."""
    validate_username(username)
    validate_domain(domain)

    if type not in SITE_TYPES:
        print(f"[red]Unknown type '{type}'. Choose from: {', '.join(SITE_TYPES)}[/red]")
        raise typer.Exit(1)
    if type == "php":
        validate_php(php)
        if not _php_installed(php):
            print(f"[red]PHP {php}-fpm is not installed[/red]")
            raise typer.Exit(1)
    if type == "node" and port is None:
        print("[red]--port is required for node sites[/red]")
        raise typer.Exit(1)
    if type in ("python-wsgi", "python-asgi") and app is None:
        print("[red]--app is required for python sites (e.g. --app myapp:application)[/red]")
        raise typer.Exit(1)

    root = BASE / username / "sites" / domain / "public_html"
    logs = BASE / username / "sites" / domain / "logs"

    sudo_mkdir(root)
    sudo_mkdir(logs)
    sudo_chown_r(BASE / username / "sites" / domain, username)
    _write_site_type(username, domain, type)

    if type == "php":
        ensure_pool(username, php)
        sock = per_user_socket(username, php)
        conf_content = build_config(domain, str(root), str(logs), str(sock))
        index = root / "index.php"
        if not index.exists():
            sudo_write(index, "<?php phpinfo();\n", owner=username)

    elif type == "static":
        conf_content = build_static_config(domain, str(root), str(logs))
        index = root / "index.html"
        if not index.exists():
            sudo_write(index, f"<h1>{domain}</h1>\n", owner=username)

    elif type == "node":
        conf_content = build_reverse_proxy_config(
            domain, str(root), str(logs), f"http://127.0.0.1:{port}"
        )
        install_service(username, domain, build_node_service(username, domain, port, entry))

    elif type == "python-wsgi":
        sock = python_socket(username, domain)
        conf_content = build_reverse_proxy_config(
            domain, str(root), str(logs), f"http://unix:{sock}:"
        )
        install_service(username, domain, build_python_wsgi_service(username, domain, app))

    elif type == "python-asgi":
        sock = python_socket(username, domain)
        conf_content = build_reverse_proxy_config(
            domain, str(root), str(logs), f"http://unix:{sock}:"
        )
        install_service(username, domain, build_python_asgi_service(username, domain, app))

    conf_path = NGINX_AVAIL / f"{domain}.conf"
    sudo_write(conf_path, conf_content)

    link = NGINX_ENABLED / f"{domain}.conf"
    if not link.exists():
        run(["sudo", "ln", "-s", str(conf_path), str(link)])

    run(["sudo", "nginx", "-t"])
    run(["sudo", "systemctl", "reload", "nginx"])

    _log("add-site", username=username, domain=domain, type=type)
    print(f"[green]Site ready:[/green] {domain}  ([cyan]{type}[/cyan])")


def delete_site(
    username: str,
    domain: str,
    purge: bool = typer.Option(False, "--purge", help="Also delete site files"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a site's nginx config and service, optionally deleting all files."""
    validate_username(username)
    validate_domain(domain)

    if not yes:
        msg = f"Delete site '{domain}'"
        if purge:
            msg += " and purge all files"
        typer.confirm(f"{msg}?", abort=True)

    php_ver = _get_site_php(domain)
    site_type = _read_site_type(username, domain)

    if site_type in ("node", "python-wsgi", "python-asgi"):
        if service_path(username, domain).exists():
            remove_service(username, domain)

    for path in [NGINX_ENABLED / f"{domain}.conf", NGINX_AVAIL / f"{domain}.conf"]:
        run(["sudo", "rm", "-f", str(path)], check=False)

    if purge:
        run(["sudo", "rm", "-rf", str(BASE / username / "sites" / domain)], check=False)

    run(["sudo", "systemctl", "reload", "nginx"])

    if site_type == "php" and php_ver:
        _cleanup_pool_if_unused(username, php_ver)

    _log("delete-site", username=username, domain=domain, purge=purge)
    print(f"[green]Site deleted:[/green] {domain}")


def list_sites(username: str = typer.Argument(None, help="Filter by username")):
    """List all sites with type, detail, enabled state, and SSL status."""
    if not BASE.exists():
        print("[yellow]No clients directory found.[/yellow]")
        return

    users = [BASE / username] if username else sorted(BASE.iterdir())

    table = Table(title="Sites", show_header=True, header_style="bold cyan")
    table.add_column("Domain")
    table.add_column("User")
    table.add_column("Type")
    table.add_column("Detail")
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
            site_type = _read_site_type(user_dir.name, domain)

            detail = "?"
            if conf_path.exists():
                text = conf_path.read_text()
                if site_type == "php":
                    m = re.search(r"php(\d+\.\d+)-fpm", text)
                    detail = m.group(1) if m else "?"
                elif site_type == "node":
                    m = re.search(r"proxy_pass http://127\.0\.0\.1:(\d+)", text)
                    detail = f":{m.group(1)}" if m else "?"
                elif site_type in ("python-wsgi", "python-asgi"):
                    detail = "unix sock"
                elif site_type == "static":
                    detail = "—"

            enabled = (
                "[green]yes[/green]"
                if (NGINX_ENABLED / f"{domain}.conf").exists()
                else "[red]no[/red]"
            )
            cert = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
            ssl = "[green]yes[/green]" if cert.exists() else "[dim]no[/dim]"
            table.add_row(domain, user_dir.name, site_type, detail, enabled, ssl)

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
    """Switch the PHP-FPM version for a PHP site."""
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
    if _read_site_type(username, domain) != "php":
        print(f"[red]{domain} is not a PHP site[/red]")
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
