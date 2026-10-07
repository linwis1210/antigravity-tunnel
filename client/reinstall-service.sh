#!/usr/bin/env bash
# Reinstall the tunnel-d1-client systemd service (run after a VM rebuild).
# The Python client and its vendored vault helper live in /home (persistent);
# only /etc/systemd/system is lost on rebuild.
set -euo pipefail
# Capture egress proxy into a 600 file (systemd gets a clean env without it).
PROXY_ENV=/home/hatch/experiments/hermuse-antigravity-poc/.proxy-env
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
cat > "$UNIT" <<'EOF'
[Unit]
Description=Hermuse D1 tunnel client (VM side, polls Cloudflare D1 -> Antigravity)
After=network-online.target antigravity-manager.service
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=/home/hatch/experiments/hermuse-antigravity-poc/.proxy-env
Environment=TUNNEL_LOCAL=http://127.0.0.1:8045
Environment=TUNNEL_POLL_MS=1000
ExecStart=/usr/bin/python3 /home/hatch/experiments/hermuse-antigravity-poc/tunnel_d1_client.py
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
echo "tunnel-d1-client reinstalled and started"
