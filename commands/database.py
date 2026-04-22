import secrets
import string
import subprocess

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from utils.shell import _log
from utils.validate import validate_username

console = Console()


def _mysql(sql: str):
    subprocess.run(["sudo", "mysql", "-e", sql], check=True)


def _mysql_out(sql: str) -> str:
    result = subprocess.run(
        ["sudo", "mysql", "-N", "-e", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _gen_password(length: int = 24) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _full_name(username: str, dbname: str) -> str:
    return f"{username}_{dbname}"


def create_db(username: str, dbname: str):
    """Create a MariaDB database and user scoped to a client."""
    validate_username(username)
    full = _full_name(username, dbname)
    password = _gen_password()

    _mysql(f"CREATE DATABASE IF NOT EXISTS `{full}`;")
    _mysql(f"CREATE USER IF NOT EXISTS '{full}'@'localhost' IDENTIFIED BY '{password}';")
    _mysql(f"GRANT ALL PRIVILEGES ON `{full}`.* TO '{full}'@'localhost';")
    _mysql("FLUSH PRIVILEGES;")

    _log("create-db", username=username, db=full)

    console.print("\n[bold green]Database created[/bold green]")
    console.print(f"  DB Name  : [cyan]{full}[/cyan]")
    console.print(f"  DB User  : [cyan]{full}[/cyan]")
    console.print(f"  Password : [yellow]{password}[/yellow]")
    console.print("  Host     : localhost\n")
    console.print("[dim]Save the password now — it will not be shown again.[/dim]\n")


def delete_db(
    username: str,
    dbname: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Drop a MariaDB database and its associated user."""
    validate_username(username)
    full = _full_name(username, dbname)

    if not yes:
        typer.confirm(f"Drop database and user '{full}'?", abort=True)

    _mysql(f"DROP DATABASE IF EXISTS `{full}`;")
    _mysql(f"DROP USER IF EXISTS '{full}'@'localhost';")
    _mysql("FLUSH PRIVILEGES;")

    _log("delete-db", username=username, db=full)
    print(f"[green]Deleted:[/green] {full}")


def list_dbs(username: str = typer.Argument(None, help="Filter by username prefix")):
    """List MariaDB databases, optionally filtered by username."""
    if username:
        validate_username(username)
        # Use parameterized-style quoting — username is already validated against [a-z0-9_]
        sql = (
            f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            f"WHERE SCHEMA_NAME LIKE '{username}\\_%';"
        )
    else:
        sql = (
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME NOT IN "
            "('information_schema','mysql','performance_schema','sys');"
        )

    output = _mysql_out(sql)
    rows = [r.strip() for r in output.strip().splitlines() if r.strip()]

    table = Table(title="Databases", show_header=True, header_style="bold cyan")
    table.add_column("Database")
    for row in rows:
        table.add_row(row)

    console.print(table)
