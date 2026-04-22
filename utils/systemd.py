from pathlib import Path

from utils.shell import run, sudo_write

_SYSTEMD_DIR = Path("/etc/systemd/system")
_RUN_DIR = Path("/run/zeropanel")


def service_name(username: str, domain: str) -> str:
    return f"zeropanel-{username}-{domain.replace('.', '-')}"


def service_path(username: str, domain: str) -> Path:
    return _SYSTEMD_DIR / f"{service_name(username, domain)}.service"


def python_socket(username: str, domain: str) -> Path:
    return _RUN_DIR / f"{username}-{domain}.sock"


def _common_headers(description: str) -> str:
    return f"""\
[Unit]
Description={description}
After=network.target

"""


def build_node_service(username: str, domain: str, port: int, entry: str = "server.js") -> str:
    root = f"/srv/clients/{username}/sites/{domain}/public_html"
    return (
        _common_headers(f"zeropanel node: {domain}")
        + f"""\
[Service]
Type=simple
User={username}
Group={username}
WorkingDirectory={root}
ExecStart=/usr/bin/node {entry}
Restart=on-failure
RestartSec=5
Environment=PORT={port}
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
"""
    )


def build_python_wsgi_service(username: str, domain: str, app: str) -> str:
    root = f"/srv/clients/{username}/sites/{domain}/public_html"
    sock = python_socket(username, domain)
    return (
        _common_headers(f"zeropanel gunicorn: {domain}")
        + f"""\
[Service]
Type=notify
User={username}
Group={username}
WorkingDirectory={root}
RuntimeDirectory=zeropanel
ExecStart=/usr/local/bin/gunicorn --bind unix:{sock} --workers 2 {app}
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""
    )


def build_python_asgi_service(username: str, domain: str, app: str) -> str:
    root = f"/srv/clients/{username}/sites/{domain}/public_html"
    sock = python_socket(username, domain)
    return (
        _common_headers(f"zeropanel uvicorn: {domain}")
        + f"""\
[Service]
Type=simple
User={username}
Group={username}
WorkingDirectory={root}
RuntimeDirectory=zeropanel
ExecStart=/usr/local/bin/uvicorn --uds {sock} {app}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    )


def install_service(username: str, domain: str, content: str):
    sudo_write(service_path(username, domain), content)
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "enable", "--now", service_name(username, domain)])


def remove_service(username: str, domain: str):
    name = service_name(username, domain)
    run(["sudo", "systemctl", "disable", "--now", name], check=False)
    run(["sudo", "rm", "-f", str(service_path(username, domain))], check=False)
    run(["sudo", "systemctl", "daemon-reload"], check=False)
