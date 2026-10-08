# Operations Notes / 运维注意事项

Operational lessons from running this tunnel in production on a cloud VM.
生产环境运维踩坑记录。

## 1. Egress proxy credentials can rotate on reboot
## 1. 出口代理凭证可能在重启后失效

**Symptom / 现象**: `tunnel-d1-client` logs `poll loop error: HTTP Error 403:
Forbidden` on every D1 poll; callers time out because queued requests are
never picked up. 隧道客户端每次轮询 D1 都报 403，调用方超时。

**Cause / 原因**: Some cloud runtimes (e.g. Muse cloud VMs) rotate the egress
proxy password on every reboot. A proxy config captured once into a static
file (e.g. `.proxy-env` at install time) goes stale after reboot.
某些云环境每次重启会轮换出口代理密码，安装时抓拍的静态代理文件在重启后
就失效了。

**Fix / 修复**: `client/reinstall-service.sh` prefers `/etc/environment`
(which the runtime refreshes at boot) when it carries proxy vars, and only
falls back to a captured file on static servers. Never hardcode a captured
proxy password into a long-lived service file.
`reinstall-service.sh` 会优先使用每次开机刷新的 `/etc/environment`，
只有静态服务器才回退到抓拍文件。不要把抓拍的代理密码写进长期服务的配置。

**How we found it / 排查过程** (2026-10-08): reproduced with the service's
exact env → `407 Proxy Authentication Required`, while the same request from
an interactive shell (fresh proxy password) succeeded. First 403 appeared at
the exact second the service restarted after a VM reboot.

## 2. VM reboot vs rebuild recovery
## 2. 重启与重建后的恢复

| Event / 事件 | What survives / 保留 | What to do / 操作 |
|---|---|---|
| Reboot / 重启 | Everything on disk, incl. `/etc/systemd/system` | Nothing — systemd restarts services (`Restart=always`). With fix #1, proxy stays valid too. |
| Rebuild / 重建 | `/home` only | Re-run `client/reinstall-service.sh` (and the Antigravity one). Unit files under `/etc/systemd/system` are lost. |

## 3. Health checks / 健康检查

```bash
# services
systemctl is-active antigravity-manager tunnel-d1-client

# backend
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8045/health  # expect 200

# client errors
journalctl -u tunnel-d1-client --since "15 min ago" -p err --no-pager

# D1 queue depth (stuck requests => client not polling)
# via Cloudflare API: SELECT COUNT(*) FROM tunnel_requests WHERE status='pending'
```

## 4. End-to-end smoke test / 端到端冒烟测试

Insert a `GET /v1/models` row into `tunnel_requests` with status `pending`,
then poll `tunnel_responses` for the same id. Expect a row within a few
seconds (status 401 is fine — it proves the client forwarded the request;
the real Worker injects the backend key server-side).
往 `tunnel_requests` 插一条 `pending` 的测试请求，再查 `tunnel_responses`
是否有回写。几秒内有响应即正常（401 也算通，说明转发链路没问题；
真实的 Worker 会在服务端注入后端 Key）。

## 5. Known limits / 已知限制

- No true SSE streaming: the full response is generated first, then returned
  (see README FAQ). 无真流式。
- Worker waits ≤ 25 s for a tunneled response; long generations may 504.
  Worker 最长等 25 秒，超长生成可能 504。
- Request/response bodies are staged in D1 (2 MB cap, 30 req/min per IP).
  请求响应体暂存 D1（2MB 上限，每 IP 每分钟 30 次）。
- `*.workers.dev` is SNI-blocked in mainland China — bind a custom domain
  for mainland callers (see README FAQ). 大陆直连 workers.dev 被墙，
  给大陆调用方绑自定义域名。
