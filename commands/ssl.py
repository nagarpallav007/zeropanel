import typer
from rich import print

from utils.shell import _log, run
from utils.validate import validate_domain


def issue_ssl(
    domain: str,
    no_www: bool = typer.Option(False, "--no-www", help="Skip the www subdomain cert"),
):
    """Issue a Let's Encrypt SSL certificate via certbot."""
    validate_domain(domain)

    cmd = ["sudo", "certbot", "--nginx", "-d", domain]
    if not no_www:
        cmd += ["-d", f"www.{domain}"]

    run(cmd)

    _log("issue-ssl", domain=domain, no_www=no_www)
    print(f"[green]SSL issued:[/green] {domain}")
