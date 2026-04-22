import subprocess
from typing import Annotated

import typer
from rich import print

from config import BASE
from utils.validate import validate_domain


def logs(
    domain: str,
    type: Annotated[str, typer.Option("--type", "-t", help="Log type: access or error")] = "access",
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 100,
):
    """Tail the nginx access or error log for a domain."""
    validate_domain(domain)

    if type not in ("access", "error"):
        print("[red]--type must be 'access' or 'error'[/red]")
        raise typer.Exit(1)

    log_path = None
    if BASE.exists():
        for user_dir in BASE.iterdir():
            candidate = user_dir / "sites" / domain / "logs" / f"{type}.log"
            if candidate.exists():
                log_path = candidate
                break

    if log_path is None:
        print(f"[red]Log file not found for domain '{domain}' (type: {type})[/red]")
        raise typer.Exit(1)

    subprocess.run(["sudo", "tail", "-n", str(lines), str(log_path)])
