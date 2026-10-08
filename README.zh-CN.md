<p align="center">
  <h1 align="center">antigravity-tunnel</h1>
</p>

<p align="center">
  <strong>🚀 为本地 Antigravity-Manager OpenAI API 提供公网 HTTPS 网关</strong><br>
  Cloudflare Workers + D1 隧道——让手机调用没有公网入口的本地模型后端。
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

## 📖 目录

- [✨ 为什么做这个？](#-为什么做这个)
- [🎯 特性](#-特性)
- [🏗️ 架构](#️-架构)
- [🚀 快速开始](#-快速开始)
- [🛠️ 技术栈](#️-技术栈)
- [❓ 常见问题](#-常见问题)
- [🙏 致谢](#-致谢)
- [🤝 参与贡献](#-参与贡献)
- [📄 开源协议](#-开源协议)
- [⚠️ 免责声明](#️-免责声明)

---

## ✨ 为什么做这个？

Antigravity-Manager 的 OpenAI 兼容 API 很好用，但只监听 `127.0.0.1`。
手机、大陆服务器、任何远程客户端都连不上。本项目用一条加固的
Cloudflare 隧道补上这一环：公网 HTTPS 进，本地 API 出，真实后端 Key
永不离开服务器。

## 🎯 特性

- 🔐 **加固入口** —— Key 认证（`X-Tunnel-Auth` 或 `Bearer PUBLIC_KEY`，
  标准 OpenAI 客户端直接把 `PUBLIC_KEY` 填进 API Key 栏即可）、
  路径/方法/请求头白名单
- 🔑 **后端 Key 常驻服务端** —— 调用方永远接触不到真实 Key
- 🚦 **限流** —— 每 Key 30 次/分钟，请求体上限 2 MiB
- 📡 **D1 队列** —— 边缘与 VM 之间无需长连接
- 🐍 **轻量客户端** —— 纯 Python，只用标准库，systemd 托管

## 🏗️ 架构

```
手机 ──HTTPS──> Cloudflare Worker ──D1──> tunnel_d1_client.py ──localhost──> Antigravity :8045
   (X-Tunnel-Auth 或 Bearer PUBLIC_KEY)   (经 API 轮询 D1)              (真实后端 Key)
```

- **Worker**（`worker/worker.js`）：公网入口 + D1 队列。校验认证与白名单，
  丢弃调用方请求头，服务端注入后端 Key，请求入队，最长 25 秒等回响应。
- **客户端**（`client/tunnel_d1_client.py`）：VM 上的 systemd 服务。经
  Cloudflare API 轮询 D1，把排队的请求转发给本地 Antigravity，再把响应
  写回 D1。
- **部署**（`deploy/deploy_worker.py`、`deploy/schema.sql`）：一键上传
  Worker（含 D1 绑定、secrets、workers.dev 路由）。
- **运行位置**：为 [Muse](https://muse.ai) 云 Linux 环境设计——
  Antigravity-Manager 与 `tunnel_d1_client.py` 以 systemd 服务跑在上面，
  Worker 对外暴露反代 API（`/v1/*`），供你的其他 agent 调用。

## 🚀 快速开始

**前置条件**：Cloudflare 账号、D1 数据库、运行中的 Antigravity-Manager
（`http://127.0.0.1:8045`）。

1. 对 D1 执行 `deploy/schema.sql` 建表。
2. 建 Cloudflare API Token（Workers Scripts Edit + D1 Edit 权限）。
3. 把 `.env.example` 复制为 `.env` 并填入账号 ID、D1 ID、API Token
  （隧道客户端也可单独用 `client/.env`）。
4. 生成 `TUNNEL_KEY`、`PUBLIC_KEY`；记下 Antigravity 的 `BACKEND_KEY`。
5. 把三个密钥存到 600 权限文件，用 `TUNNEL_KEY_FILE` /
  `PUBLIC_KEY_FILE` / `BACKEND_KEY_FILE` 指向它们，然后运行
  `python3 deploy/deploy_worker.py`。
5. VM 上执行 `bash client/reinstall-service.sh` 安装 systemd 服务
  （VM 重建后重跑一次即可）。
6. 手机上（Cherry Studio / OpenCode / 任意 OpenAI 客户端）：Base URL
   `https://<worker>.<subdomain>.workers.dev/v1`，API Key = `PUBLIC_KEY`。

## 🛠️ 技术栈

- **边缘**：Cloudflare Workers（ES Module）、Cloudflare D1（SQLite）
- **VM 客户端**：Python 3（仅标准库 `urllib`，无第三方依赖）
- **部署工具**：Python + Cloudflare REST API（不需要 wrangler）
- **后端**：Antigravity-Manager（OpenAI 兼容 `/v1/*`）

## ❓ 常见问题

<details>
<summary><b>Q: 手机返回 404 "No Workers script was found for this host"？</b></summary>

纯 Cloudflare API 上传 **不会**自动开通 `workers.dev` 路由（wrangler 会）。
修复：

```bash
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<id>/workers/scripts/<name>/subdomain" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  --data '{"enabled":true}'
```

`deploy/deploy_worker.py` 每次部署都会自动执行这一步。
</details>

<details>
<summary><b>Q: 大陆连不上 workers.dev？</b></summary>

`*.workers.dev` 被 GFW SNI 阻断。可选：给 Worker 绑自定义域名
（SNI 不同，通常可达），或把后端直接跑在海外 VPS 上。
</details>

<details>
<summary><b>Q: VM 重建后服务没了？</b></summary>

重建会清空 `/etc/systemd/system`，但 `/home` 保留。重跑：
`bash ~/muse-antigravity-test/reinstall-service.sh`（Antigravity）和
`bash ~/experiments/hermuse-antigravity-poc/reinstall-service.sh`
（隧道客户端）。
</details>

<details>
<summary><b>Q: `stream:true` 不流式？</b></summary>

长轮询架构限制：先完整生成，再一次性返回 SSE 文本，无真流式。
</details>

## 🙏 致谢

- 隧道协议（D1 队列、poll/respond 流程）借鉴自
  [Hermuse](https://github.com/imkofty/Hermuse)（作者
  [imkofty](https://github.com/imkofty)）。
- 本地后端为 [Antigravity-Manager](https://github.com/Draculabo/AntigravityManager)
  （作者 [Draculabo](https://github.com/Draculabo)）。

## 🤝 参与贡献

欢迎提 Issue / PR。请勿提交密钥——`.gitignore` 已排除密钥文件，
推送前用 `git status` 再确认一次。

## 📄 开源协议

[MIT](LICENSE)

第三方声明：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## ⚠️ 免责声明

> [!WARNING]
> 本项目转发至 Antigravity-Manager，其通过非官方途径访问 Google 服务，
> 可能违反 Google 服务条款并导致账号受限。请自行斟酌风险，使用可承受
> 损失的账号。按"现状"提供，不作任何保证。

---

<p align="center">
  如果这个项目对你有帮助，请给它点个 ⭐ Star！
</p>
