import re
import typer
from rich import print

from config import PHP_VALID

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DOMAIN_RE = re.compile(r"^([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def validate_username(username: str):
    if not USERNAME_RE.match(username):
        print("[red]Invalid username. Use lowercase letters, digits, underscores; must start with a letter.[/red]")
        raise typer.Exit(1)


def validate_domain(domain: str):
    if not DOMAIN_RE.match(domain.lower()):
        print(f"[red]Invalid domain: {domain}[/red]")
        raise typer.Exit(1)


def validate_php(version: str):
    if version not in PHP_VALID:
        print(f"[red]PHP {version} not supported. Valid versions: {', '.join(sorted(PHP_VALID))}[/red]")
        raise typer.Exit(1)
