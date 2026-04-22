def build_config(domain: str, root: str, logs: str, sock: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain} www.{domain};

    root {root};
    index index.php index.html;
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
