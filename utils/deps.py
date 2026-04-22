"""Dependency detection and installation helpers for setup-server."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.shell import run


# ── Checkers ──────────────────────────────────────────────────────────────────

def _dpkg_installed(package: str) -> bool:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", package],
        capture_output=True, text=True,
    )
    return "install ok installed" in result.stdout


def _binary_exists(binary: str) -> bool:
    return subprocess.run(
        ["which", binary], capture_output=True
    ).returncode == 0


def _php_versions_installed() -> list[str]:
    found = []
    for d in sorted(Path("/etc/php").iterdir()) if Path("/etc/php").exists() else []:
        if d.is_dir() and (d / "fpm").exists():
            found.append(d.name)
    return found


def _pip_installed(package: str) -> bool:
    return subprocess.run(
        ["python3", "-m", "pip", "show", package],
        capture_output=True,
    ).returncode == 0


# ── Package definitions ───────────────────────────────────────────────────────

@dataclass
class AptDep:
    package: str
    label: str
    check: callable        # () -> bool — True means already present
    install_packages: list[str] | None = None  # None means same as package


@dataclass
class ManualDep:
    label: str
    check: callable
    hint: str              # shown when not found


APT_DEPS: list[AptDep] = [
    AptDep(
        "nginx", "nginx",
        check=lambda: _dpkg_installed("nginx"),
    ),
    AptDep(
        "mariadb-server", "MariaDB",
        check=lambda: _dpkg_installed("mariadb-server"),
    ),
    AptDep(
        "certbot", "certbot",
        check=lambda: _dpkg_installed("certbot"),
        install_packages=["certbot", "python3-certbot-nginx"],
    ),
    AptDep(
        "python3-certbot-nginx", "certbot-nginx plugin",
        check=lambda: _dpkg_installed("python3-certbot-nginx"),
    ),
    AptDep(
        "quota", "quota tools",
        check=lambda: _dpkg_installed("quota"),
    ),
]

MANUAL_DEPS: list[ManualDep] = [
    ManualDep(
        "Node.js",
        check=lambda: _binary_exists("node"),
        hint="curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt install nodejs",
    ),
    ManualDep(
        "Gunicorn (WSGI)",
        check=lambda: _binary_exists("gunicorn") or _pip_installed("gunicorn"),
        hint="pip install gunicorn",
    ),
    ManualDep(
        "Uvicorn (ASGI)",
        check=lambda: _binary_exists("uvicorn") or _pip_installed("uvicorn"),
        hint="pip install 'uvicorn[standard]'",
    ),
]


# ── Install ───────────────────────────────────────────────────────────────────

def apt_update():
    run(["sudo", "apt-get", "update", "-qq"])


def apt_install(packages: list[str]):
    run([
        "sudo", "apt-get", "install", "-y", "-qq",
        "--no-install-recommends", *packages,
    ])


# ── Quota fstab helper ────────────────────────────────────────────────────────

def modify_fstab_for_quota(filesystem: str = "/") -> bool:
    """Add usrquota to the fstab options for filesystem. Returns True if changed."""
    result = subprocess.run(["sudo", "cat", "/etc/fstab"], capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines(keepends=True)
    new_lines = []
    changed = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        fields = stripped.split()
        if len(fields) >= 4 and fields[1] == filesystem:
            opts = fields[3].split(",")
            if "usrquota" not in opts:
                opts.append("usrquota")
                # Replace options field in the line, preserving original whitespace layout
                new_line = re.sub(
                    r"^(\s*\S+\s+\S+\s+\S+\s+)\S+",
                    lambda m: m.group(1) + ",".join(opts),
                    line,
                )
                new_lines.append(new_line)
                changed = True
                continue
        new_lines.append(line)

    if changed:
        # Back up before touching fstab
        subprocess.run(["sudo", "cp", "/etc/fstab", "/etc/fstab.zeropanel.bak"], check=True)
        subprocess.run(
            ["sudo", "tee", "/etc/fstab"],
            input="".join(new_lines),
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    return changed
