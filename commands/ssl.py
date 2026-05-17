import re
from pathlib import Path

import typer
from rich import print

from utils.nginx import set_limit
from utils.shell import _log, run
from utils.validate import validate_domain

_NGINX_AVAIL = Path("/etc/nginx/sites-available")


def issue_ssl(
    domain: str,
    no_www: bool = typer.Option(False, "--no-www", help="Skip the www subdomain cert"),
):
    """Issue a Let's Encrypt SSL certificate via certbot."""
    validate_domain(domain)

    # Preserve the upload limit before certbot restructures the vhost
    conf = _NGINX_AVAIL / f"{domain}.conf"
    existing = conf.read_text() if conf.exists() else ""
    m = re.search(r"client_max_body_size\s+(\S+);", existing)
    limit = m.group(1) if m else "1G"

    cmd = ["sudo", "certbot", "--nginx", "-d", domain]
    if not no_www:
        cmd += ["-d", f"www.{domain}"]
    run(cmd)

    # certbot may have split the vhost into multiple blocks — re-apply limit to all
    if conf.exists():
        set_limit(conf, limit)
        run(["sudo", "nginx", "-t"])
        run(["sudo", "systemctl", "reload", "nginx"])

    _log("issue-ssl", domain=domain, no_www=no_www)
    print(f"[green]SSL issued:[/green] {domain}")
