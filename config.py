from pathlib import Path

BASE = Path("/srv/clients")
NGINX_AVAIL = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
LOG_FILE = Path("/var/log/panel.log")

PHP_VALID = {"8.1", "8.2", "8.3", "8.4"}
DEFAULT_PHP = "8.2"

# User isolation
SSHD_PANEL_CONF  = Path("/etc/ssh/sshd_config.d/zeropanel.conf")
CRON_DENY        = Path("/etc/cron.deny")
SFTP_GROUP       = "sftp-users"
DEV_GROUP        = "dev-users"
RESTRICTED_SHELL = Path("/opt/panel/bin/restricted-shell")

# Per-user hard limits written to /etc/security/limits.conf
LIMIT_NPROC  = 50
LIMIT_NOFILE = 512
LIMIT_FSIZE  = 524288  # 512 MB in KB
