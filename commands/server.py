from rich import print

from utils.system import bootstrap


def init_server():
    """One-time server bootstrap: create isolation groups, write sshd config, install restricted-shell."""
    print("[bold]Bootstrapping zeropanel server isolation...[/bold]")
    bootstrap()
    print("[green]Done.[/green] Run [bold]sudo panel create-user <name>[/bold] to add your first client.")
