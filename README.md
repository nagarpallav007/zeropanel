# zeropanel

A lightweight, open-source hosting panel for self-hosters and VPS operators — no web UI, no bloat, just a single `sudo panel` command.

Provision users, nginx vhosts, PHP-FPM, Node.js, Python (WSGI/ASGI), static sites, Let's Encrypt SSL, and MariaDB databases from the terminal. Built for people who prefer CLI over dashboards and want full control of their server without installing cPanel or Plesk.

---

## Why zeropanel?

- **No web UI** — everything lives in your terminal and your config files
- **No agent processes** — it runs, does its job, and exits
- **Readable** — ~700 lines of Python you can audit in an afternoon
- **Opinionated but escapable** — sensible defaults, all overridable
- **Production-safe** — passwords never touch the process list, inputs are validated before any side effect, all actions are logged to `/var/log/panel.log`

---

## Current support

| Stack | Status |
|---|---|
| PHP (8.1 – 8.4) via PHP-FPM | ✅ Supported |
| Node.js (systemd + reverse proxy) | ✅ Supported |
| Python WSGI — Gunicorn | ✅ Supported |
| Python ASGI — Uvicorn | ✅ Supported |
| Static sites | ✅ Supported |
| Go (reverse proxy) | 🔜 Roadmap |

---

## Requirements

- Ubuntu 22.04 / 24.04 (Debian-based)
- nginx
- PHP-FPM (any of 8.1, 8.2, 8.3, 8.4) — for PHP sites
- Node.js — for Node.js sites
- Gunicorn (`pip install gunicorn`) — for Python WSGI sites
- Uvicorn (`pip install uvicorn`) — for Python ASGI sites
- certbot with the nginx plugin
- MariaDB
- Python 3.10+

---

## Install

```bash
git clone https://github.com/nagarpallav007/zeropanel /opt/panel
cd /opt/panel
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Create the system-wide `panel` command:

```bash
sudo tee /usr/local/bin/panel > /dev/null << 'EOF'
#!/bin/bash
cd /opt/panel
exec /opt/panel/venv/bin/python /opt/panel/panel.py "$@"
EOF
sudo chmod +x /usr/local/bin/panel
```

Verify:

```bash
sudo panel --help
```

---

## Usage

### Users

```bash
sudo panel create-user <username>                       # prompts for password securely
sudo panel delete-user <username> [--purge] [--yes]    # --purge removes files + nginx configs
sudo panel list-users
```

### Sites

```bash
# PHP (default)
sudo panel add-site <username> <domain>
sudo panel add-site <username> <domain> --php 8.3

# Node.js — reverse-proxied, managed as a systemd service
sudo panel add-site <username> <domain> --type node --port 3000
sudo panel add-site <username> <domain> --type node --port 3000 --entry app.js

# Python WSGI (Gunicorn)
sudo panel add-site <username> <domain> --type python-wsgi --app myapp:application

# Python ASGI (Uvicorn)
sudo panel add-site <username> <domain> --type python-asgi --app myapp:app

# Static HTML/CSS/JS — no backend
sudo panel add-site <username> <domain> --type static

# Manage sites
sudo panel delete-site <username> <domain> [--purge] [--yes]
sudo panel list-sites [username]
sudo panel enable-site <domain>
sudo panel disable-site <domain>
sudo panel set-php <domain> <version>          # PHP sites only
```

### SSL

```bash
sudo panel issue-ssl <domain>           # issues cert for domain + www.domain
sudo panel issue-ssl <domain> --no-www  # domain only
```

### Databases

```bash
sudo panel create-db <username> <dbname>        # creates scoped DB + user, prints credentials once
sudo panel delete-db <username> <dbname> [--yes]
sudo panel list-dbs [username]
```

### Logs

```bash
sudo panel logs <domain>                        # tails access log (last 100 lines)
sudo panel logs <domain> --type error --lines 50
```

---

## Directory layout

Each user gets an isolated directory tree:

```
/srv/clients/
└── username/
    ├── sites/
    │   └── example.com/
    │       ├── public_html/    ← document root
    │       └── logs/           ← access.log, error.log
    └── backups/
```

nginx configs live in the standard locations:

```
/etc/nginx/sites-available/example.com.conf
/etc/nginx/sites-enabled/example.com.conf   ← symlink
```

---

## Roadmap

- [x] **Node.js sites** — systemd service + nginx reverse proxy
- [x] **Python WSGI / ASGI** — Gunicorn / Uvicorn with auto-generated systemd services
- [x] **Static sites** — zero-PHP nginx config for pure HTML/JS/CSS deployments
- [ ] **Go sites** — reverse proxy to a compiled binary managed as a systemd service
- [ ] **Backup command** — `panel backup-site` to tar + compress to `/srv/clients/{user}/backups/`
- [ ] **Restore command** — `panel restore-site` from a backup archive
- [ ] **MySQL import** — `panel import-db` from a `.sql` file
- [ ] **List SSL expiry** — show cert expiry dates in `list-sites`

---

## Contributing

Contributions are welcome. A few ground rules:

1. **Open an issue first** for anything beyond a small bug fix — alignment before code saves time.
2. **One concern per PR** — don't bundle unrelated changes.
3. **Conventional commits** — `feat:`, `fix:`, `refactor:`, `chore:`, subject line only.
4. **No new dependencies** without discussion — the goal is to keep the install lightweight.
5. **Test on a real VPS** before opening a PR — this tool runs as root and touches live system config.

If you're adding a new site type (Node, Python, Go), open an issue with your proposed `build_config()` template and systemd unit approach first.

---

## License

MIT — see [LICENSE](LICENSE).
