import re
from pathlib import Path


def set_limit(conf_path: Path, size: str):
    """Set client_max_body_size in every server block of an nginx config. Idempotent."""
    from utils.shell import sudo_write
    text = conf_path.read_text()
    if re.search(r"client_max_body_size\s+\S+;", text):
        text = re.sub(r"client_max_body_size\s+\S+;", f"client_max_body_size {size};", text)
    else:
        text = re.sub(
            r"([ \t]*server_name\s+[^;]+;)",
            rf"\1\n    client_max_body_size {size};",
            text,
        )
    sudo_write(conf_path, text)


def build_config(domain: str, root: str, logs: str, sock: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain} www.{domain};

    root {root};
    index index.php index.html;
    charset utf-8;

    client_max_body_size 1G;
    server_tokens off;

    access_log {logs}/access.log;
    error_log  {logs}/error.log;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_vary on;
    gzip_min_length 1000;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml application/xml+rss text/javascript
               image/svg+xml font/woff2;

    # Block dot-files: .env, .git, .htaccess, etc. — allow .well-known for SSL renewal
    location ~ /\\.(?!well-known) {{
        deny all;
    }}

    # Block sensitive file types from direct access
    location ~* \\.(env|log|sql|bak|sh|bash|key|pem)$ {{
        deny all;
    }}

    # Block project metadata files
    location ~* ^/(composer\\.(json|lock)|package(-lock)?\\.json|yarn\\.lock|\\.gitignore|Makefile|Dockerfile)$ {{
        deny all;
    }}

    # Static asset caching
    location ~* \\.(jpg|jpeg|png|gif|ico|webp|svg|woff|woff2|ttf|css|js)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }}

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{sock};
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_hide_header X-Powered-By;
        fastcgi_read_timeout 300;
    }}
}}
"""
