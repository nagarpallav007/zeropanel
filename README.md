# panel

CLI hosting panel for a shared-hosting VPS. Manages nginx vhosts, PHP-FPM versions, Let's Encrypt SSL, Linux system users, and MariaDB databases — all via a single `sudo panel` command.

## Requirements

- Ubuntu/Debian VPS
- nginx, PHP-FPM (8.1–8.4), certbot, MariaDB
- Python 3.10+

## Install

```bash
git clone <repo> /opt/panel
cd /opt/panel
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Create the system-wide wrapper:

```bash
cat > /usr/local/bin/panel << 'EOF'
#!/bin/bash
cd /opt/panel
exec /opt/panel/venv/bin/python /opt/panel/panel.py "$@"
EOF
chmod +x /usr/local/bin/panel
```

## Commands

### Users
```bash
sudo panel create-user <username>              # prompts for password
sudo panel delete-user <username> [--purge] [--yes]
sudo panel list-users
```

### Sites
```bash
sudo panel add-site <username> <domain> [--php 8.2]
sudo panel delete-site <username> <domain> [--purge] [--yes]
sudo panel list-sites [username]
sudo panel enable-site <domain>
sudo panel disable-site <domain>
sudo panel set-php <domain> <version>
```

### SSL
```bash
sudo panel issue-ssl <domain> [--no-www]
```

### Databases
```bash
sudo panel create-db <username> <dbname>      # prints credentials once
sudo panel delete-db <username> <dbname> [--yes]
sudo panel list-dbs [username]
```

### Logs
```bash
sudo panel logs <domain> [--type access|error] [--lines 100]
```

## Security notes

- Passwords are passed to `chpasswd` via stdin — never appear in process list or shell history.
- Usernames and domains are validated by regex before any system calls.
- All actions are logged to `/var/log/panel.log`.
- Database names and users are scoped as `{username}_{dbname}` to prevent cross-client access.
