#!/usr/bin/env python3
"""Deploy the hardened tunnel worker to Cloudflare Workers via API.

  1. PUT /accounts/{id}/workers/scripts/antigravity-tunnel
     multipart: metadata (main_module + d1 binding) + worker.js
  2. PUT /accounts/{id}/workers/scripts/antigravity-tunnel/secrets (x3)

Secrets are read from local files (chmod 600), never printed.
Requires token permission: Account -> Workers Scripts -> Edit.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response  # noqa: E402

ACCOUNT = "ada664e899f8a6812710448982f0acd7"
WORKER = "antigravity-tunnel"
API = "https://api.cloudflare.com/client/v4"
D1_ID = "9d7ad41f-8d1c-4ea5-bc02-c8bd7b02600b"
WORKER_JS = os.path.expanduser("~/experiments/hermuse-antigravity-poc/deploy/worker.js")

SECRETS = {
    "TUNNEL_KEY": os.path.expanduser("~/.tunnel-key"),
    "PUBLIC_KEY": os.path.expanduser("~/experiments/hermuse-antigravity-poc/.public-key"),
    "BACKEND_KEY": os.path.expanduser("~/muse-antigravity-test/secrets/api_key"),
}


def read_secret(path):
    with open(path) as f:
        return f.read().strip()


def cfapi(method, path, data=None, ctype="application/json"):
    body = data if isinstance(data, bytes) else (
        json.dumps(data).encode() if data is not None else None)
    headers = {"Content-Type": ctype} if body else {}
    req = urllib.request.Request(API + path, method=method, data=body, headers=headers)
    add_surrogate_to_request(req, "custom.cloudflare", allowed_hosts=["api.cloudflare.com"])
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return read_json_response(resp)
    except urllib.error.HTTPError as e:
        print(f"API {method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")
        raise SystemExit(1)


def main():
    with open(WORKER_JS, "rb") as f:
        script = f.read()
    print(f"worker.js: {len(script)} bytes")

    metadata = {
        "main_module": "worker.js",
        "compatibility_date": "2025-01-01",
        "workers_dev": True,
        "bindings": [
            {"type": "d1", "name": "DB", "id": D1_ID},
        ],
    }

    boundary = "----" + uuid.uuid4().hex
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="metadata"\r\n'
    body += b"Content-Type: application/json\r\n\r\n"
    body += json.dumps(metadata).encode() + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="worker.js"; filename="worker.js"\r\n'
    body += b"Content-Type: application/javascript+module\r\n\r\n"
    body += script + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    d = cfapi("PUT", f"/accounts/{ACCOUNT}/workers/scripts/{WORKER}", body,
              f"multipart/form-data; boundary={boundary}")
    if not d.get("success"):
        print("script upload failed:", json.dumps(d.get("errors"))[:300])
        raise SystemExit(1)
    print("worker uploaded:", d["result"].get("id", WORKER))

    for name, path in SECRETS.items():
        value = read_secret(path)
        d = cfapi("PUT", f"/accounts/{ACCOUNT}/workers/scripts/{WORKER}/secrets",
                  {"name": name, "text": value, "type": "secret_text"})
        ok = d.get("success")
        print(f"secret {name}: {'ok' if ok else 'FAILED'}")
        if not ok:
            raise SystemExit(1)

    print("DONE - worker live at: https://" + WORKER + ".ada664e899f8a6812710448982f0acd7.workers.dev")

    # Enable the workers.dev route (raw API does NOT do this automatically;
    # without it the URL 404s even though the script exists — Cloudflare 1042
    # "No Workers script was found for this host on workers.dev").
    d = cfapi("POST", f"/accounts/{ACCOUNT}/workers/scripts/{WORKER}/subdomain",
              {"enabled": True})
    ok = d.get("success") and d.get("result", {}).get("enabled")
    print(f"workers.dev route: {'enabled' if ok else 'FAILED'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
