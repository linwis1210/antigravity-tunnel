<p align="center">
  <h1 align="center">antigravity-tunnel</h1>
</p>

<p align="center">
  <strong>🚀 Public HTTPS gateway for a local Antigravity-Manager OpenAI API</strong><br>
  Cloudflare Workers + D1 tunnel — call a model backend with no public inbound, from your phone.
</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/linwis1210/antigravity-tunnel/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/linwis1210/antigravity-tunnel?style=flat-square" alt="License" />
  </a>
  <a href="https://github.com/linwis1210/antigravity-tunnel/stargazers">
    <img src="https://img.shields.io/github/stars/linwis1210/antigravity-tunnel?style=flat-square" alt="Stars" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Cloudflare_Workers-F38020?style=for-the-badge&logo=cloudflare&logoColor=white" alt="Cloudflare Workers" />
  <img src="https://img.shields.io/badge/Cloudflare_D1-F38020?style=for-the-badge&logo=cloudflare&logoColor=white" alt="Cloudflare D1" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
</p>

---

## 📖 Table of Contents

- [✨ Why antigravity-tunnel?](#-why-antigravity-tunnel)
- [🎯 Features](#-features)
- [🏗️ Architecture](#️-architecture)
- [🚀 Quick Start](#-quick-start)
- [🛠️ Tech Stack](#️-tech-stack)
- [❓ FAQ](#-faq)
- [🙏 Acknowledgments](#-acknowledgments)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [⚠️ Disclaimer](#️-disclaimer)

---

## ✨ Why antigravity-tunnel?

Antigravity-Manager exposes a great OpenAI-compatible API — but only on
`127.0.0.1`. Your phone, your mainland server, and any remote client can't
reach it. This project bridges that gap with a hardened Cloudflare tunnel:
public HTTPS in, local API out, with the real backend key never leaving the
server.

## 🎯 Features

- 🔐 **Hardened ingress** — key auth (`X-Tunnel-Auth` or `Bearer PUBLIC_KEY`,
  so standard OpenAI clients just work), path/method/header allowlists
- 🔑 **Backend key stays server-side** — callers never see the real API key
- 🚦 **Rate limiting** — 30 req/min per key, 2 MiB body cap
- 📡 **D1-backed queue** — no persistent connection needed between edge and VM
- 🐍 **Dependency-light client** — pure-Python, stdlib only, systemd-managed

## 🏗️ Architecture

```
phone ──HTTPS──> Cloudflare Worker ──D1──> tunnel_d1_client.py ──localhost──> Antigravity :8045
   (X-Tunnel-Auth or Bearer PUBLIC_KEY)   (polls D1 via API)          (real backend key)
```

- **Worker** (`worker/worker.js`): public ingress + D1 queue. Validates auth,
  allowlists, drops caller headers, injects the backend key server-side,
  enqueues the request, waits ≤25 s for the tunneled response.
- **Client** (`client/tunnel_d1_client.py`): systemd service on the VM. Polls
  D1 via the Cloudflare API, forwards queued requests to local Antigravity,
  writes responses back to D1.
- **Deploy** (`deploy/deploy_worker.py`, `deploy/schema.sql`): one-shot Worker
  upload (script + D1 binding + secrets + workers.dev route).
- **Where it runs**: designed for the [Muse](https://muse.ai) cloud Linux VM —
  Antigravity-Manager and `tunnel_d1_client.py` run there as systemd services,
  while the Worker exposes the reverse-proxy API (`/v1/*`) for your other
  agents to call.

## 🚀 Quick Start

**Prerequisites**: Cloudflare account, D1 database, running Antigravity-Manager
on `http://127.0.0.1:8045`.

1. Apply `deploy/schema.sql` to your D1 database.
2. Create a Cloudflare API token (Workers Scripts Edit + D1 Edit).
3. Copy `.env.example` to `.env` and fill in your account ID, D1 ID and API token
   (also used by `client/.env` for the tunnel client).
4. Generate `TUNNEL_KEY` and `PUBLIC_KEY`; note your Antigravity `BACKEND_KEY`.
5. Save the three secrets to 600-permission files and point
   `TUNNEL_KEY_FILE` / `PUBLIC_KEY_FILE` / `BACKEND_KEY_FILE` at them,
   then run `python3 deploy/deploy_worker.py`.
5. On the VM: `bash client/reinstall-service.sh` (installs the systemd unit;
   re-run after any VM rebuild).
6. On your phone (Cherry Studio / OpenCode / any OpenAI client): base URL
   `https://<worker>.<subdomain>.workers.dev/v1`, API key = `PUBLIC_KEY`.

## 🛠️ Tech Stack

- **Edge**: Cloudflare Workers (ES module), Cloudflare D1 (SQLite)
- **VM client**: Python 3 (stdlib only — `urllib`, no third-party deps)
- **Deploy tooling**: Python + Cloudflare REST API (no wrangler required)
- **Backend**: Antigravity-Manager (OpenAI-compatible `/v1/*`)

## ❓ FAQ

<details>
<summary><b>Q: Phone gets 404 "No Workers script was found for this host"?</b></summary>

The raw Cloudflare API does **not** enable the `workers.dev` route on upload
(wrangler does it for you). Fix:

```bash
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<id>/workers/scripts/<name>/subdomain" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  --data '{"enabled":true}'
```

`deploy/deploy_worker.py` already does this on every deploy.
</details>

<details>
<summary><b>Q: Can't reach workers.dev from mainland China?</b></summary>

`*.workers.dev` is SNI-blocked by the GFW. Options: bind a custom domain to
the Worker (different SNI, usually reachable), or run the backend on an
overseas VPS instead.
</details>

<details>
<summary><b>Q: Services gone after a VM rebuild?</b></summary>

Rebuilds wipe `/etc/systemd/system` but keep `/home`. Re-run:
`bash ~/muse-antigravity-test/reinstall-service.sh` (Antigravity) and
`bash ~/experiments/hermuse-antigravity-poc/reinstall-service.sh`
(tunnel client).
</details>

<details>
<summary><b>Q: `stream:true` doesn't stream?</b></summary>

Architectural limit of the long-poll design: the full response is generated
first, then returned as complete SSE text. No true streaming.
</details>

## 🙏 Acknowledgments

- Tunnel protocol (D1 queue, poll/respond flow) adapted from
  [Hermuse](https://github.com/imkofty/Hermuse) by
  [imkofty](https://github.com/imkofty).
- Local backend is [Antigravity-Manager](https://github.com/Draculabo/AntigravityManager)
  by [Draculabo](https://github.com/Draculabo).

## 🤝 Contributing

Issues and PRs are welcome. Please don't commit secrets — `.gitignore`
already excludes key files; double-check with `git status` before pushing.

## 📄 License

[MIT](LICENSE)

Third-party attributions: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## ⚠️ Disclaimer

> [!WARNING]
> This project forwards to Antigravity-Manager, which accesses Google
> services through unofficial means. That may violate Google's Terms of
> Service and risk account restriction. Use at your own discretion, with
> accounts you can afford to lose. Provided "as-is", no warranty.

---

<p align="center">
  If this project helps you, please give it a ⭐ Star!
</p>
