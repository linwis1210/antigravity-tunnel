#!/usr/bin/env python3
"""Deploy the hardened tunnel worker to Cloudflare Workers via API.

Config: set env vars directly, or copy .env.example to the repo root as .env
(the client/.env is also read):

  CF_ACCOUNT_ID          Cloudflare account ID
  CF_D1_ID               D1 database UUID (bound to the worker as DB)
  CF_API_TOKEN           API token (Workers Scripts Edit + D1 Edit)
  CF_WORKER_NAME         worker script name (default: antigravity-tunnel)
  CF_WORKERS_SUBDOMAIN   your account's workers.dev subdomain
  WORKER_JS              path to worker.js (default: ../worker/worker.js)
  TUNNEL_KEY_FILE / PUBLIC_KEY_FILE / BACKEND_KEY_FILE
                         paths to the three secret files (chmod 600)

Steps:
  1. PUT /accounts/{id}/workers/scripts/{name} (metadata + D1 binding + worker.js)
  2. PUT /accounts/{id}/workers/scripts/{name}/secrets (TUNNEL_KEY, PUBLIC_KEY, BACKEND_KEY)
  3. POST .../subdomain {"enabled": true} — enables the workers.dev route
     (the raw API does NOT do this automatically; without it the URL returns
     Cloudflare 1042 "No Workers script was found for this host on workers.dev")

Secrets are read from local files (chmod 600), never printed.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client"))
from cf_auth import auth_request, load_dotenv, read_json_response, require_config  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
load_dotenv()  # also try client/.env
require_config("CF_ACCOUNT_ID", "CF_D1_ID")

ACCOUNT = os.environ["CF_ACCOUNT_ID"]
WORKER = os.environ.get("CF_WORKER_NAME", "antigravity-tunnel")
SUBDOMAIN = os.environ.get("CF_WORKERS_SUBDOMAIN", "")
API = "https://api.cloudflare.com/client/v4"
D1_ID = os.environ["CF_D1_ID"]
_HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_JS = os.environ.get("WORKER_JS",
    os.path.join(_HERE, "..", "worker", "worker.js"))

SECRETS = {
    "TUNNEL_KEY": os.path.expanduser(os.environ.get("TUNNEL_KEY_FILE", "~/.tunnel-key")),
    "PUBLIC_KEY": os.path.expanduser(os.environ.get("PUBLIC_KEY_FILE", "~/.public-key")),
    "BACKEND_KEY": os.path.expanduser(os.environ.get("BACKEND_KEY_FILE", "~/.antigravity-api-key")),
}


def read_secret(path):
    if not os.path.isfile(path):
        raise SystemExit(f"Secret file not found: {path}\n"
                         f"Set the corresponding *_FILE env var (see .env.example).")
    with open(path) as f:
        return f.read().strip()


def cfapi(method, path, data=None, ctype="application/json"):
    body = data if isinstance(data, bytes) else (
        json.dumps(data).encode() if data is not None else None)
    headers = {"Content-Type": ctype} if body else {}
    req = urllib.request.Request(API + path, method=method, data=body, headers=headers)
    auth_request(req)
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

    if SUBDOMAIN:
        print("DONE - worker live at: https://" + WORKER + "." + SUBDOMAIN + ".workers.dev")
    else:
        print("DONE - worker uploaded. Set CF_WORKERS_SUBDOMAIN to print the public URL.")

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
