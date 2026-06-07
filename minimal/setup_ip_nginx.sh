#!/usr/bin/env bash
set -euo pipefail

UPSTREAM="${UPSTREAM:-http://127.0.0.1:8000}"
CONF="/etc/nginx/sites-available/default"

[ "$EUID" -eq 0 ] || { echo "Run with sudo"; exit 1; }

command -v nginx >/dev/null || {
  apt-get update
  apt-get install -y nginx
}

cat > "$CONF" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass $UPSTREAM;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
EOF

ln -sfn "$CONF" /etc/nginx/sites-enabled/default

nginx -t
systemctl enable nginx >/dev/null
systemctl reload nginx || systemctl restart nginx

command -v ufw >/dev/null && ufw status | grep -q active && ufw allow 'Nginx HTTP' || true

echo "OK: nginx proxies http://<public-ip>/ -> $UPSTREAM/"
