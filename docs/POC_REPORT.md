# Hermuse → Existing Antigravity Local POC Report

**测试日期**：2026-10-02
**最终技术结论：PASS**（非流式请求；真 SSE 流式不支持是架构级限制）

## Existing Antigravity

- Process: `antigravity-tools --headless` (pid 8267)
- Listening address: **127.0.0.1:8045**（非 0.0.0.0，无需整改）
- Version: v4.8.8
- Direct /v1/models: **PASS**（32 个模型）
- Gemini 3.8 Flash model ID: `gemini-3.8-flash`（实际路由 `gemini-3.8-flash-high`）
- Direct completion: **PASS**，精确输出 `Antigravity direct works.`（3.2s）
- 偏离说明：方案要求"不要重启"，但服务当时处于用户暂停后的停止状态，故执行了 `systemctl enable --now` 启动；**未修改任何配置、凭证、OAuth、账号**。

## Hermuse

- Repository: `imkofty/Hermuse`（MIT，63 stars，测试当天仍在更新）
- Commit: `beb7ed54d09dcbcfb4286f1d8a400bad8db6e7b2`
- Tunnel client: `tunnel-client.mjs`（88 行，**原样复制，未修改**）
- LOCAL: `http://127.0.0.1:8045`
- Relay: 本地 simulator `127.0.0.1:19090`（RAM only，模拟 `POST /__tunnel/poll` + `POST /__tunnel/respond`）
- 偏离说明：真实客户端从**文件**读 key（`TUNNEL_KEY_FILE`），不是 `TUNNEL_KEY` 环境变量；响应字段是 `status_code` 不是 `status`。Simulator 按真实协议实现。

## Tunnel Tests（10/10 PASS）

| # | 测试 | 结果 |
|---|---|---|
| 1 | tunneled /v1/models status | PASS（200=200） |
| 2 | tunneled /v1/models 列表一致性 | PASS（32 个全一致，延迟 ~0s） |
| 3 | tunneled chat status | PASS（200=200） |
| 4 | tunneled chat content | PASS（精确 `Hermuse Antigravity tunnel works.`） |
| 5 | tunneled chat schema | PASS（JSON keys 全一致，finish_reason=stop，有 usage，1.7s） |
| 6 | HTTP status preserved | PASS（direct 404 = tunnel 404） |
| 7 | UTF-8 preserved | PASS（`中文传输正常` 无乱码） |
| 8 | tool_calls preserved | PASS（`get_current_time`，name/type/arguments 全一致） |
| 9 | 100KB request body | PASS（200，9.9s） |
| 10 | streaming（分析） | 见下 |

Direct vs Tunnel 对比：HTTP 状态、模型 ID、JSON 结构、assistant 内容、finish_reason、usage、tool_calls **全部一致**，tunnel 未破坏 OpenAI-compatible schema。

延迟说明：5s/15s/30s 未做注入式模拟（需改 backend，方案禁止）；实测 tunneled chat 1.7s、100KB 9.9s。注意真实部署的 edge（`[[path]].js`）25s 无响应即 504，长 reasoning 请求是风险点。

## Streaming

- Direct Antigravity streaming：支持（此前已验证 SSE chunk + [DONE]）
- Hermuse true streaming：**NOT SUPPORTED**
- Buffered response：是（2.0s 后一次性返回完整 SSE body）
- Reason：`tunnel-client.mjs:56` `await r.arrayBuffer()` 全量缓冲后才 respond，架构级限制，不改协议无解

## Security Findings（基于只读代码审计）

- **Authorization 处理**：`[[path]].js` 转发**所有** headers（含 Authorization）→ 明文存 D1。Relay 运营方（Cloudflare / D1 访问者）可见。
- **Cookie 处理**：同样转发、同样明文存储（仅过滤 host/connection/content-length）。
- **Request body**：明文存 D1（base64）。
- **Response body**：明文存 D1（base64）。
- **Wildcard route**：是。`[[path]].js` 是 catch-all，任意 `/*` 路径、任意 method 均可入队。
- **公开 ingress 认证**：**无**。`[[path]].js` 没有任何 key/鉴权检查，知道 Pages URL 的任何人可向 tunnel 注入任意请求。tunnel key 只保护 client↔relay，不保护 public→relay。**这是当前实现最大的安全洞。**
- **Admin 暴露**：LOCAL 指向 Antigravity 根地址时，`/api/*` 管理接口经 tunnel 完全可达（取决于请求者是否持有 Antigravity 自身的 web password；但路径本身无额外隔离）。
- **Credential 暴露**：本地 POC 的 relay 日志经检查零泄露（只记 id/method/path/status/size）；但真实部署中 D1 即明文存储。
- **Cleanup**：`[[path]].js` 完成后立即删除 req/res；`poll.js` 清理 120s 前的残留；25s 无响应 504 并删请求。

## Final Technical Result

**PASS** — Hermuse long-poll tunnel 可透明代理现有 Antigravity-Manager 的 OpenAI-compatible API（非流式请求）。

## 对第 26 节六个问题的回答

1. **已有 Antigravity 是否无需修改就能作为 Hermuse LOCAL backend？** 是。零修改，仅需 `TUNNEL_LOCAL` 指向它。
2. **`/v1/models` 能否透明经过 tunnel？** 能。32 个模型与 direct 完全一致。
3. **`stream=false` 的 chat 能否正常经过 tunnel？** 能。内容、schema、usage 全保持。
4. **Tool Calling 是否保持完整？** 是。`tool_calls`/`name`/`arguments`/`type` 全保持。
5. **当前最大技术限制是不是 SSE streaming？** 是。`arrayBuffer()` 全缓冲是架构级限制。
6. **是否值得进入下一阶段（Cloudflare Gateway + 双 API Key + Path/Header allowlist + Rate limit）？** 技术上值得，但三个前置警告：
   - a. 本地 POC **证明不了** Cloudflare 阶段：Pages Functions 的 CPU/时长限制、D1 延迟是全新未知数；
   - b. 公开 ingress **零认证**必须先修：path allowlist + 双 Key 不是可选项，是上线前提；
   - c. 25s edge timeout 对长 reasoning 请求是硬伤，需在网关层设计异步/轮询取结果；
   - d. 原则层面：这是你之前"隧道禁令"的另一种形态（relay 在你自己 Cloudflare 账号上），你已首肯"安全的隧道可以"，那就按此口径推进。

**按方案要求：本地 POC 成功，停止，不自行部署公网版本。** 下一步（Cloudflare Gateway）等你明确指令。

## 认证漏洞修复（2026-10-02 ~10:30-11:00）

用户批准后实施。针对审计发现的"公开 ingress 零认证"漏洞：
- 新文件 `hardened_relay.py`（本地 relay 127.0.0.1:19091）：公开 ingress 要求 `X-Tunnel-Auth` 公钥（401）；path 精确 allowlist 仅 `/v1/models`、`/v1/chat/completions`（403）；method 仅 GET/POST；调用方 headers 全部丢弃、backend Authorization 由服务端注入（双 Key 设计）；body 上限 2MB（413）；限流 30 req/min（429）；同步等待 tunnel 响应并返回真实状态码。
- 安全回归测试 8/8 PASS：无 key→401、错 key→401、`/api/accounts`→403、DELETE→403、服务端注入后 /v1/models 200（32 个模型）、伪造 Authorization/Cookie 被剥离且 backend 照常工作、burst 40 次触发 14 个 429、relay 日志零 credential 泄露。
- 另产出 Cloudflare 可部署版 `hardened-path.js`（D1 限流，wrangler secret 存三把 key），供 phase 2 用。
- 公钥 `.public-key`（600 权限）；tunnel client 本体未改动。测试后脚手架进程已清理，Antigravity 保持运行。
