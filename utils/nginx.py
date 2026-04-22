def _common_block(domain: str, root: str, logs: str) -> str:
    return f"""\
server {{
    listen 80;
    server_name {domain} www.{domain};

    root {root};
    charset utf-8;

    client_max_body_size 64M;
    server_tokens off;

    access_log {logs}/access.log;
    error_log  {logs}/error.log;

    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";

    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
"""


def build_config(domain: str, root: str, logs: str, sock: str) -> str:
    """PHP-FPM vhost."""
    return (
        _common_block(domain, root, logs)
        + f"""\
    index index.php index.html;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{sock};
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }}

    location ~ /\\.ht {{
        deny all;
    }}
}}
"""
    )


def build_static_config(domain: str, root: str, logs: str) -> str:
    """Static file vhost — no PHP, no proxy."""
    return (
        _common_block(domain, root, logs)
        + """\
    index index.html index.htm;

    location / {
        try_files $uri $uri/ =404;
    }

    location ~ /\\.ht {
        deny all;
    }
}
"""
    )


def build_reverse_proxy_config(domain: str, root: str, logs: str, upstream: str) -> str:
    """Reverse-proxy vhost for Node.js and Python (WSGI/ASGI).

    upstream — either 'http://127.0.0.1:PORT' or 'http://unix:/path/to/socket'
    """
    return (
        _common_block(domain, root, logs)
        + f"""\
    location / {{
        proxy_pass {upstream};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }}

    location ~ /\\.ht {{
        deny all;
    }}
}}
"""
    )
