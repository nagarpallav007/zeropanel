import subprocess

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from utils.deps import (
    APT_DEPS,
    MANUAL_DEPS,
    apt_install,
    apt_update,
    modify_fstab_for_quota,
    _php_versions_installed,
)
from utils.system import bootstrap, quotas_enabled

console = Console()


def init_server():
    """One-time panel bootstrap: isolation groups, sshd config, restricted-shell."""
    print("[bold]Bootstrapping zeropanel server isolation...[/bold]")
    bootstrap()
    print("[green]Done.[/green] Run [bold]sudo panel create-user <name>[/bold] to add your first client.")


def setup_server():
    """Check all server dependencies and install any that are missing."""
    print("[bold]Checking server requirements...[/bold]\n")

    # ── APT packages ──────────────────────────────────────────────────────────
    apt_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    apt_table.add_column("Package")
    apt_table.add_column("Status")

    missing_apt: list[str] = []
    for dep in APT_DEPS:
        if dep.check():
            apt_table.add_row(dep.label, "[green]✔ installed[/green]")
        else:
            apt_table.add_row(dep.label, "[red]✘ missing[/red]")
            pkgs = dep.install_packages or [dep.package]
            for p in pkgs:
                if p not in missing_apt:
                    missing_apt.append(p)

    # ── PHP versions ──────────────────────────────────────────────────────────
    php_versions = _php_versions_installed()
    if php_versions:
        apt_table.add_row("PHP-FPM", f"[green]✔ {', '.join(php_versions)}[/green]")
    else:
        apt_table.add_row("PHP-FPM", "[yellow]⚠  not found — see below[/yellow]")

    console.print(apt_table)

    # ── Install missing apt packages ──────────────────────────────────────────
    if missing_apt:
        print(f"\n[bold]Installing:[/bold] {', '.join(missing_apt)}")
        apt_update()
        apt_install(missing_apt)
        print("[green]✔ done[/green]")
    else:
        print("\n[green]All apt packages already installed.[/green]")

    # ── PHP guidance ──────────────────────────────────────────────────────────
    if not php_versions:
        print(
            "\n[yellow]PHP-FPM not found.[/yellow] Install with:\n"
            "  [dim]sudo add-apt-repository ppa:ondrej/php\n"
            "  sudo apt install php8.2-fpm php8.2-cli php8.2-mysql \\\n"
            "    php8.2-curl php8.2-gd php8.2-mbstring php8.2-xml php8.2-zip[/dim]"
        )

    # ── Manual / pip deps ─────────────────────────────────────────────────────
    manual_missing = [(d.label, d.hint) for d in MANUAL_DEPS if not d.check()]
    if manual_missing:
        print("\n[bold]Optional dependencies not found:[/bold]")
        for label, hint in manual_missing:
            print(f"  [yellow]✘ {label}[/yellow]\n    [dim]{hint}[/dim]")

    # ── Quota status ──────────────────────────────────────────────────────────
    print()
    if quotas_enabled():
        print("[green]✔ Disk quotas are active.[/green]")
    else:
        print(
            "[yellow]⚠  Disk quotas not enabled.[/yellow] "
            "Run [bold]sudo panel enable-quotas[/bold] to configure them "
            "(or quotas will be silently skipped per user)."
        )

    print("\n[bold green]Setup check complete.[/bold green]")


def enable_quotas(
    filesystem: str = typer.Option("/", "--filesystem", "-f", help="Filesystem to enable quotas on"),
):
    """Configure filesystem quotas: update fstab, remount, quotacheck, quotaon."""
    import shutil
    if not shutil.which("quotacheck"):
        print("[red]quota package not installed.[/red] Run: sudo apt install quota")
        raise typer.Exit(1)

    if quotas_enabled(filesystem):
        print(f"[green]✔ Disk quotas already active on {filesystem}[/green]")
        return

    print(f"[bold]Enabling disk quotas on {filesystem}...[/bold]")

    changed = modify_fstab_for_quota(filesystem)
    if changed:
        print("[green]✔ Added usrquota to /etc/fstab[/green]  (backup: /etc/fstab.zeropanel.bak)")
    else:
        print("[dim]  /etc/fstab already has usrquota[/dim]")

    try:
        subprocess.run(["sudo", "mount", "-o", "remount", filesystem], check=True)
        print(f"[green]✔ Remounted {filesystem}[/green]")
    except subprocess.CalledProcessError:
        print(
            f"[yellow]⚠  Live remount of {filesystem} failed — a reboot will activate the fstab change.[/yellow]\n"
            "[dim]   Safe to reboot; fstab has been updated.[/dim]"
        )

    try:
        subprocess.run(["sudo", "quotacheck", "-cum", filesystem], check=True)
        print("[green]✔ quotacheck passed[/green]")
    except subprocess.CalledProcessError:
        print(
            "[yellow]⚠  quotacheck failed.[/yellow]\n"
            "[dim]   This can occur on VPS providers where the kernel or filesystem\n"
            "   does not support quotas (e.g. some btrfs/LVM setups, OpenVZ containers).\n"
            "   Quota operations will be silently skipped — nothing else is affected.[/dim]"
        )
        return

    try:
        subprocess.run(["sudo", "quotaon", filesystem], check=True)
        print(f"[green]✔ Quotas active on {filesystem}[/green]")
    except subprocess.CalledProcessError:
        print("[yellow]⚠  quotaon failed — try rebooting and re-running this command.[/yellow]")
        return

    print("\n[bold green]Disk quotas are now active.[/bold green]")
