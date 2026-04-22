from pathlib import Path

BASE = Path("/srv/clients")
NGINX_AVAIL = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
LOG_FILE = Path("/var/log/panel.log")

PHP_VALID = {"8.1", "8.2", "8.3", "8.4"}
DEFAULT_PHP = "8.2"

# Disk quotas
DEFAULT_QUOTA    = "2G"
QUOTA_FILESYSTEM = "/"  # change if /srv is a separate partition
