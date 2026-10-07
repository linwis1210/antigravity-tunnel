#!/usr/bin/env python3
"""D1-backed tunnel client (VM side).

Polls the Cloudflare D1 queue DIRECTLY via api.cloudflare.com, forwards queued
requests to the local Antigravity API, and writes responses back.

Config: set CF_ACCOUNT_ID, CF_D1_ID, CF_API_TOKEN as env vars, or copy
.env.example to client/.env and fill it in. Optional: TUNNEL_LOCAL
(default http://127.0.0.1:8045), TUNNEL_POLL_MS (default 1000).

Why not via the Worker's /__tunnel/poll? The sandbox egress proxy is itself a
Cloudflare Worker, and Cloudflare blocks Worker -> *.workers.dev fetches
(error 1042). api.cloudflare.com is NOT affected, so we talk D1 directly.

Flow (shared D1 with the Worker ingress):
  Worker (phone -> D1): INSERT INTO tunnel_requests ... status='pending'
  This client: SELECT pending -> UPDATE to 'claimed' -> POST to Antigravity
               -> INSERT OR REPLACE INTO tunnel_responses
  Worker (D1 -> phone): SELECT FROM tunnel_responses WHERE id=? (25s poll loop)
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_auth import auth_request, load_dotenv, read_json_response, require_config  # noqa: E402

load_dotenv()  # optional: reads client/.env
require_config("CF_ACCOUNT_ID", "CF_D1_ID")

ACCOUNT = os.environ["CF_ACCOUNT_ID"]
D1_ID = os.environ["CF_D1_ID"]
API = "https://api.cloudflare.com/client/v4"
LOCAL = os.environ.get("TUNNEL_LOCAL", "http://127.0.0.1:8045")
POLL_INTERVAL = float(os.environ.get("TUNNEL_POLL_MS", "1000")) / 1000.0
BATCH = 4


def d1(sql, params=None):
    """Run a D1 query via the Cloudflare API. Returns list of result rows."""
    payload = {"sql": sql}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        f"{API}/accounts/{ACCOUNT}/d1/database/{D1_ID}/query",
        method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    auth_request(req)
    with urllib.request.urlopen(req, timeout=30) as resp:
        d = read_json_response(resp)
    if not d.get("success"):
        raise RuntimeError(f"D1 error: {json.dumps(d.get('errors'))[:200]}")
    out = []
    for r in d.get("result", []):
        out.extend(r.get("results", []))
    return out


def forward_to_backend(method, path, headers, body_b64):
    """Forward one request to local Antigravity. Returns (status, headers_dict, body_b64)."""
    data = base64.b64decode(body_b64) if body_b64 else None
    req = urllib.request.Request(LOCAL + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            rh = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read()
        rh = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return e.code, rh, base64.b64encode(raw).decode() if raw else None
    # Strip hop-by-hop / problematic headers before storing
    for h in ("content-encoding", "transfer-encoding", "connection"):
        rh.pop(h, None)
    return resp.status, rh, base64.b64encode(raw).decode() if raw else None


def cleanup(now):
    d1("DELETE FROM tunnel_requests WHERE created_at < ?",
       [now - 120000])
    d1("DELETE FROM tunnel_responses WHERE created_at < ?",
       [now - 120000])


def main():
    print(f"tunnel-d1-client: polling D1, backend={LOCAL}", flush=True)
    while True:
        try:
            now = int(time.time() * 1000)
            cleanup(now)
            rows = d1(
                "SELECT id, method, path, headers, body FROM tunnel_requests "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                [BATCH])
            if rows:
                ids = [r["id"] for r in rows]
                ph = ",".join("?" for _ in ids)
                d1(f"UPDATE tunnel_requests SET status='claimed' "
                   f"WHERE id IN ({ph}) AND status='pending'", ids)
                for r in rows:
                    rid, method, path = r["id"], r["method"], r["path"]
                    try:
                        headers = json.loads(r["headers"] or "{}")
                        sc, rh, rb = forward_to_backend(method, path, headers, r["body"])
                        d1("INSERT OR REPLACE INTO tunnel_responses "
                           "(id, status_code, headers, body, created_at) VALUES (?,?,?,?,?)",
                           [rid, sc, json.dumps(rh), rb, int(time.time() * 1000)])
                        print(f"{method} {path} -> {sc}", flush=True)
                    except Exception as e:
                        print(f"forward {rid} failed: {e}", flush=True)
                        d1("INSERT OR REPLACE INTO tunnel_responses "
                           "(id, status_code, headers, body, created_at) VALUES (?,?,?,?,?)",
                           [rid, 502, "{}", None, int(time.time() * 1000)])
            else:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"poll loop error: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
