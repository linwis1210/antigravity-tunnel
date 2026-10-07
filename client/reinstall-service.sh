#!/usr/bin/env bash
# Reinstall the tunnel-d1-client systemd service (re-run after a VM rebuild:
# only /etc/systemd/system is lost; the repo files on /home persist).
#
# Usage: bash client/reinstall-service.sh [client_dir]
#   client_dir defaults to the directory containing this script.
# The client reads Cloudflare config from env vars or client/.env
# (see .env.example) — copy .env.example to client/.env and fill it in first.
set -euo pipefail
CLIENT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
CLIENT_PY="$CLIENT_DIR/tunnel_d1_client.py"
[ -f "$CLIENT_PY" ] || { echo "not found: $CLIENT_PY"; exit 1; }

# Capture egress proxy into a 600 file (systemd gets a clean env without it).
PROXY_ENV="$CLIENT_DIR/.proxy-env"
{
  echo "https_proxy=${https_proxy:-}"
  echo "HTTPS_PROXY=${HTTPS_PROXY:-}"
  echo "http_proxy=${http_proxy:-}"
  echo "HTTP_PROXY=${HTTP_PROXY:-}"
  echo "no_proxy=${no_proxy:-localhost,127.0.0.1}"
  echo "NO_PROXY=${NO_PROXY:-localhost,127.0.0.1}"
} > "$PROXY_ENV"
chmod 600 "$PROXY_ENV"

UNIT=/etc/systemd/system/tunnel-d1-client.service
cat > "$UNIT" <<EOF
[Unit]
Description=Antigravity D1 tunnel client (VM side, polls Cloudflare D1 -> Antigravity)
After=network-online.target antigravity-manager.service
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=$PROXY_ENV
Environment=TUNNEL_LOCAL=http://127.0.0.1:8045
Environment=TUNNEL_POLL_MS=1000
ExecStart=/usr/bin/python3 $CLIENT_PY
WorkingDirectory=$CLIENT_DIR
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tunnel-d1-client.service
sleep 2
systemctl is-active tunnel-d1-client.service
echo "tunnel-d1-client reinstalled and started (client dir: $CLIENT_DIR)"
