"""Portable Cloudflare API auth helper.

Picks the first available auth mode:

1. ``CF_API_TOKEN`` (env var or ``client/.env``) -> ``Authorization: Bearer <token>``.
   Works for everyone. Create a token at
   https://dash.cloudflare.com/profile/api-tokens with:
     - Account -> Workers Scripts -> Edit
     - Account -> D1 -> Edit
2. ``dynamic_credentials`` (Muse Secure-Vault helper, bundled as
   ``client/dynamic_credentials.py``). Only used when no API token is set;
   it is specific to the author's environment and can be ignored by others.

Usage::

    from cf_auth import auth_request, read_json_response, load_dotenv

    load_dotenv()                      # optional: load client/.env
    req = urllib.request.Request(url, method="POST", data=body,
                                 headers={"Content-Type": "application/json"})
    auth_request(req)                  # attaches auth for api.cloudflare.com
    with urllib.request.urlopen(req) as resp:
        data = read_json_response(resp)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from http.client import HTTPResponse

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def load_dotenv(path: str | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no override).

    Simple parser: ignores blanks and lines starting with '#', strips
    surrounding quotes. Only fills keys that are not already set.
    """
    path = path or os.path.join(_HERE, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _token() -> str | None:
    return os.environ.get("CF_API_TOKEN")


def auth_request(req: urllib.request.Request,
                 credential_name: str = "custom.cloudflare") -> urllib.request.Request:
    """Attach Cloudflare API auth to a request for api.cloudflare.com.

    Raises RuntimeError if no auth mode is available.
    """
    url = req.full_url
    host = urllib.request.urlparse(url).hostname or ""
    if host != "api.cloudflare.com":
        raise RuntimeError(f"cf_auth only targets api.cloudflare.com, got {host}")

    token = _token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        return req

    # Fallback: author's environment (Muse vault-backed surrogates).
    try:
        from dynamic_credentials import (  # noqa: E402
            add_surrogate_to_request,
        )
    except ImportError as e:
        raise RuntimeError(
            "No Cloudflare auth available: set CF_API_TOKEN (env or client/.env), "
            "or provide dynamic_credentials.py."
        ) from e
    add_surrogate_to_request(req, credential_name, allowed_hosts=["api.cloudflare.com"])
    return req


def read_json_response(response: HTTPResponse) -> dict:
    """Parse a JSON HTTP response body. Portable; no vault dependency."""
    raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw) if raw.strip() else {}


def require_config(*names: str) -> None:
    """Fail fast with a helpful message when required env vars are missing."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(
            "Missing required config: " + ", ".join(missing) + "\n"
            "Set them as env vars or copy .env.example to client/.env and fill it in."
        )
