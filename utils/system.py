import re
import subprocess
from pathlib import Path

from config import (
    CRON_DENY,
    DEV_GROUP,
    LIMIT_FSIZE,
    LIMIT_NOFILE,
    LIMIT_NPROC,
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
ALLOWED_RE='^(php[0-9.]*|composer|git|ls|pwd|mkdir|cp|mv|rm|nano|vim|unzip|tar|wget|curl)( .*)?$'

if [[ -z "$SSH_ORIGINAL_COMMAND" ]]; then
    echo "Interactive shells are not permitted on this server."
    exit 1
fi

if [[ "$SSH_ORIGINAL_COMMAND" =~ $ALLOWED_RE ]]; then
    cd "/srv/clients/$(id -un)" && exec /bin/bash -c "$SSH_ORIGINAL_COMMAND"
else
    echo "Command not permitted: $SSH_ORIGINAL_COMMAND"
    exit 1
fi
"""


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
    if not RESTRICTED_SHELL.exists():
        run(["sudo", "mkdir", "-p", str(RESTRICTED_SHELL.parent)])
        sudo_write(RESTRICTED_SHELL, _RESTRICTED_SHELL)
        run(["sudo", "chmod", "755", str(RESTRICTED_SHELL)])
        run(["sudo", "chown", "root:root", str(RESTRICTED_SHELL)])


def bootstrap():
    """Idempotent: create groups, write sshd config, write restricted-shell."""
    ensure_group(SFTP_GROUP)
    ensure_group(DEV_GROUP)
    ensure_sshd_config()
    ensure_restricted_shell()


def add_to_cron_deny(username: str):
    # Read current contents via sudo to handle /etc/cron.deny being root-owned
    result = subprocess.run(
        ["sudo", "cat", str(CRON_DENY)],
        capture_output=True,
        text=True,
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
        ["sudo", "cat", str(CRON_DENY)],
        capture_output=True,
        text=True,
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


def write_limits(username: str):
    limits_conf = Path("/etc/security/limits.conf")
    result = subprocess.run(
        ["sudo", "cat", str(limits_conf)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Avoid duplicate entries
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
        ["sudo", "cat", str(limits_conf)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return
    # Remove the zeropanel block for this user (marker line + 3 limit lines)
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
