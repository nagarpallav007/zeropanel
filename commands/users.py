import subprocess

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from config import BASE, DEFAULT_QUOTA, NGINX_AVAIL, NGINX_ENABLED
from utils.phpfpm import pools_for_user, remove_pool
from utils.shell import _log, run, sudo_chown_r, sudo_mkdir
from utils.system import remove_quota, set_quota
from utils.validate import validate_username

console = Console()


def create_user(
    username: str,
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, confirmation_prompt=True
    ),
    quota: str = typer.Option(
        DEFAULT_QUOTA,
        "--quota",
        help="Disk quota soft limit (e.g. 1G, 500M). Hard limit = soft + 20%.",
    ),
):
    """Create a system user and provision their home directory."""
    validate_username(username)

    result = subprocess.run(["id", username], capture_output=True)
    if result.returncode != 0:
        run(["sudo", "useradd", "-m", "-s", "/bin/bash", username])

    subprocess.run(
        ["sudo", "chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        check=True,
    )

    sudo_mkdir(BASE / username / "sites")
    sudo_mkdir(BASE / username / "backups")
    # Top-level dir stays root:root 755 for ChrootDirectory compatibility
    run(["sudo", "chown", "root:root", str(BASE / username)])
    run(["sudo", "chmod", "755", str(BASE / username)])
    sudo_chown_r(BASE / username / "sites", username)
    sudo_chown_r(BASE / username / "backups", username)

    set_quota(username, quota)

    _log("create-user", username=username, quota=quota)
    print(f"[green]User ready:[/green] {username}  quota={quota}")


def delete_user(
    username: str,
    purge: bool = typer.Option(False, "--purge", help="Delete all files and nginx configs"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a system user, optionally purging all their files and site configs."""
    validate_username(username)

    if not yes:
        msg = f"Delete user '{username}'"
        if purge:
            msg += " and purge all files + nginx configs"
        typer.confirm(f"{msg}?", abort=True)

    # Remove all PHP-FPM pools before userdel
    for version, _ in pools_for_user(username):
        remove_pool(username, version)

    run(["sudo", "userdel", "-r", username], check=False)
    remove_quota(username)

    if purge:
        user_path = BASE / username
        if user_path.exists():
            sites_dir = user_path / "sites"
            if sites_dir.exists():
                for site_dir in sites_dir.iterdir():
                    domain = site_dir.name
                    for path in [
                        NGINX_ENABLED / f"{domain}.conf",
                        NGINX_AVAIL / f"{domain}.conf",
                    ]:
                        run(["sudo", "rm", "-f", str(path)], check=False)
        run(["sudo", "rm", "-rf", str(user_path)], check=False)
        run(["sudo", "systemctl", "reload", "nginx"], check=False)

    _log("delete-user", username=username, purge=purge)
    print(f"[green]User deleted:[/green] {username}")


def list_users():
    """List all provisioned users with their site count and disk usage."""
    if not BASE.exists():
        print("[yellow]No clients directory found.[/yellow]")
        return

    table = Table(title="Users", show_header=True, header_style="bold cyan")
    table.add_column("Username")
    table.add_column("Sites", justify="right")
    table.add_column("Disk Usage", justify="right")

    for user_dir in sorted(BASE.iterdir()):
        if not user_dir.is_dir():
            continue
        sites_dir = user_dir / "sites"
        site_count = len(list(sites_dir.iterdir())) if sites_dir.exists() else 0
        result = subprocess.run(
            ["sudo", "du", "-sh", str(user_dir)],
            capture_output=True,
            text=True,
        )
        disk = result.stdout.split()[0] if result.returncode == 0 else "?"
        table.add_row(user_dir.name, str(site_count), disk)

    console.print(table)
