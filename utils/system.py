import re
import subprocess
from pathlib import Path

from config import (
    CRON_DENY,
    DEV_GROUP,
    LIMIT_FSIZE,
    LIMIT_NOFILE,
    LIMIT_NPROC,
    QUOTA_FILESYSTEM,
    RESTRICTED_SHELL,
    SFTP_GROUP,
    SSHD_PANEL_CONF,
)
from utils.shell import run, sudo_write

_SSHD_BLOCK = """\
# Managed by zeropanel — do not edit manually

Match Group sftp-users
    ChrootDirectory /srv/clients/%u
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no

Match Group dev-users
    ForceCommand /opt/panel/bin/restricted-shell
    AllowTcpForwarding no
    X11Forwarding no
"""

_RESTRICTED_SHELL = """\
#!/bin/bash
# Allowed: website tooling only. No editors, no network tools.
ALLOWED_RE='^(php[0-9.]*|composer|git|ls|pwd|mkdir|cp|mv|rm|unzip|tar)( .*)?$'

if [[ -z "$SSH_ORIGINAL_COMMAND" ]]; then
    echo "Interactive shells are not permitted on this server."
    exit 1
fi

if [[ "$SSH_ORIGINAL_COMMAND" =~ $ALLOWED_RE ]]; then
    cd "/srv/clients/$(id -un)" || exit 1
    read -ra CMD <<< "$SSH_ORIGINAL_COMMAND"
    exec "${CMD[@]}"
else
    echo "Command not permitted: $SSH_ORIGINAL_COMMAND"
    exit 1
fi
"""


# ── Bootstrap ────────────────────────────────────────────────────────────────

def ensure_group(name: str):
    result = subprocess.run(["getent", "group", name], capture_output=True)
    if result.returncode != 0:
        run(["sudo", "groupadd", "--system", name])


def ensure_sshd_config():
    if not SSHD_PANEL_CONF.exists():
        run(["sudo", "mkdir", "-p", str(SSHD_PANEL_CONF.parent)])
        sudo_write(SSHD_PANEL_CONF, _SSHD_BLOCK)
        run(["sudo", "systemctl", "reload", "ssh"])


def ensure_restricted_shell():
    run(["sudo", "mkdir", "-p", str(RESTRICTED_SHELL.parent)])
    sudo_write(RESTRICTED_SHELL, _RESTRICTED_SHELL)
    run(["sudo", "chmod", "755", str(RESTRICTED_SHELL)])
    run(["sudo", "chown", "root:root", str(RESTRICTED_SHELL)])


def bootstrap():
    """Idempotent: create isolation groups, write sshd config, write restricted-shell."""
    ensure_group(SFTP_GROUP)
    ensure_group(DEV_GROUP)
    ensure_sshd_config()
    ensure_restricted_shell()


# ── Cron ─────────────────────────────────────────────────────────────────────

def add_to_cron_deny(username: str):
    result = subprocess.run(
        ["sudo", "cat", str(CRON_DENY)], capture_output=True, text=True
    )
    existing = result.stdout if result.returncode == 0 else ""
    if username not in existing.splitlines():
        subprocess.run(
            ["sudo", "tee", "-a", str(CRON_DENY)],
            input=f"{username}\n",
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )


def remove_from_cron_deny(username: str):
    result = subprocess.run(
        ["sudo", "cat", str(CRON_DENY)], capture_output=True, text=True
    )
    if result.returncode != 0:
        return
    lines = [l for l in result.stdout.splitlines() if l.strip() != username]
    subprocess.run(
        ["sudo", "tee", str(CRON_DENY)],
        input="\n".join(lines) + "\n",
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


# ── limits.conf ──────────────────────────────────────────────────────────────

def write_limits(username: str):
    limits_conf = Path("/etc/security/limits.conf")
    result = subprocess.run(
        ["sudo", "cat", str(limits_conf)], capture_output=True, text=True, check=True
    )
    if f"# zeropanel:{username}" in result.stdout:
        return
    entry = (
        f"\n# zeropanel:{username}\n"
        f"{username}  hard  nproc   {LIMIT_NPROC}\n"
        f"{username}  hard  nofile  {LIMIT_NOFILE}\n"
        f"{username}  hard  fsize   {LIMIT_FSIZE}\n"
    )
    subprocess.run(
        ["sudo", "tee", "-a", str(limits_conf)],
        input=entry,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def remove_limits(username: str):
    limits_conf = Path("/etc/security/limits.conf")
    result = subprocess.run(
        ["sudo", "cat", str(limits_conf)], capture_output=True, text=True
    )
    if result.returncode != 0:
        return
    cleaned = re.sub(
        rf"\n# zeropanel:{re.escape(username)}\n(?:.*\n){{3}}",
        "\n",
        result.stdout,
    )
    subprocess.run(
        ["sudo", "tee", str(limits_conf)],
        input=cleaned,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


# ── Disk quotas ──────────────────────────────────────────────────────────────

def _parse_size_to_kb(size: str) -> int:
    """Parse '1G', '500M', '100K' into 1-KB blocks for setquota."""
    s = size.upper().strip()
    if s.endswith("G"):
        return int(float(s[:-1]) * 1024 * 1024)
    if s.endswith("M"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("K"):
        return int(float(s[:-1]))
    return int(s)


def quotas_enabled(filesystem: str = QUOTA_FILESYSTEM) -> bool:
    """Return True if user quotas are active on the given filesystem."""
    result = subprocess.run(
        ["sudo", "quotaon", "-p", filesystem],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and "user quota on" in result.stdout.lower()


def set_quota(username: str, soft: str, filesystem: str = QUOTA_FILESYSTEM):
    """Set disk quota. Hard limit = soft + 20%. Silently skips if quotas are not enabled."""
    from rich import print as rprint
    if not quotas_enabled(filesystem):
        rprint(
            f"[yellow]⚠  Disk quotas not active on {filesystem} — skipping quota for {username}.[/yellow]\n"
            "[dim]   Run [bold]sudo panel enable-quotas[/bold] to configure filesystem quotas.[/dim]"
        )
        return
    soft_kb = _parse_size_to_kb(soft)
    hard_kb = int(soft_kb * 1.2)
    try:
        run([
            "sudo", "setquota", "-u", username,
            str(soft_kb), str(hard_kb), "0", "0", filesystem,
        ])
    except Exception:
        rprint(f"[yellow]⚠  Could not set quota for {username} — continuing without quota.[/yellow]")


def remove_quota(username: str, filesystem: str = QUOTA_FILESYSTEM):
    """Remove disk quota for a user. No-op if quotas are not enabled."""
    if not quotas_enabled(filesystem):
        return
    run(
        ["sudo", "setquota", "-u", username, "0", "0", "0", "0", filesystem],
        check=False,
    )
