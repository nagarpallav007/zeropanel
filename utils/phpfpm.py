from pathlib import Path

from utils.shell import run, sudo_mkdir, sudo_write


def pool_path(username: str, version: str) -> Path:
    return Path(f"/etc/php/{version}/fpm/pool.d/{username}.conf")


def per_user_socket(username: str, version: str) -> Path:
    return Path(f"/run/php/php{version}-fpm-{username}.sock")


def build_pool(username: str, version: str) -> str:
    sock = per_user_socket(username, version)
    tmp = f"/srv/clients/{username}/tmp"
    return f"""[{username}]
user  = {username}
group = {username}
listen = {sock}
listen.owner = www-data
listen.group = www-data

pm = ondemand
pm.max_children = 5
pm.process_idle_timeout = 10s
request_terminate_timeout = 30s

php_admin_value[open_basedir]      = /srv/clients/{username}/:/tmp/
php_admin_flag[allow_url_fopen]    = Off
php_admin_value[disable_functions] = exec,system,shell_exec,passthru,proc_open,popen,proc_nice
php_admin_value[upload_tmp_dir]    = {tmp}
php_admin_value[session.save_path] = {tmp}
"""


def ensure_pool(username: str, version: str):
    """Write the per-user pool file if it doesn't exist, then reload PHP-FPM."""
    path = pool_path(username, version)
    if path.exists():
        return
    tmp = Path(f"/srv/clients/{username}/tmp")
    sudo_mkdir(tmp)
    run(["sudo", "chown", f"{username}:{username}", str(tmp)])
    run(["sudo", "chmod", "700", str(tmp)])
    sudo_write(path, build_pool(username, version))
    run(["sudo", "systemctl", "reload", f"php{version}-fpm"])


def remove_pool(username: str, version: str):
    """Remove the per-user pool file and reload PHP-FPM."""
    run(["sudo", "rm", "-f", str(pool_path(username, version))], check=False)
    run(["sudo", "systemctl", "reload", f"php{version}-fpm"], check=False)


def pools_for_user(username: str) -> list[tuple[str, Path]]:
    """Return [(version, pool_path), …] for all existing pools belonging to a user."""
    found = []
    for php_dir in Path("/etc/php").iterdir():
        if not php_dir.is_dir():
            continue
        p = pool_path(username, php_dir.name)
        if p.exists():
            found.append((php_dir.name, p))
    return found
