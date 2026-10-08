// Hermuse hardened tunnel worker (Cloudflare Workers).
// Single-file port of the Pages Functions: __tunnel/poll.js, __tunnel/respond.js,
// and the hardened [[path]].js ingress.
//
// Bindings / secrets (set via API, never in code):
//   env.DB          - D1 database (tunnel_requests / tunnel_responses)
//   env.TUNNEL_KEY  - tunnel client <-> worker key
//   env.PUBLIC_KEY  - public callers key, header X-Tunnel-Auth
//   env.BACKEND_KEY - Antigravity API key, injected server-side
//
// Routes:
//   POST /__tunnel/poll     - local tunnel client long-polls for queued requests
//   POST /__tunnel/respond  - local tunnel client posts backend responses
//   *                       - hardened public ingress (allowlisted paths only)

const PATH_ALLOWLIST = new Set(["/v1/models", "/v1/chat/completions"]);
const METHOD_ALLOWLIST = new Set(["GET", "POST"]);
const MAX_BODY = 2 * 1024 * 1024;
const RATE_LIMIT_PER_MIN = 30;
const WAIT_MS = 25000;
const POLL_WAIT_MS = 20000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/__tunnel/poll" && request.method === "POST") {
      return handlePoll(request, env);
    }
    if (url.pathname === "/__tunnel/respond" && request.method === "POST") {
      return handleRespond(request, env);
    }
    return handleIngress(request, env);
  },
};

// Local client long-poll: hold up to ~20s until a request is queued.
async function handlePoll(request, env) {
  const { key, limit } = await request.json().catch(() => ({}));
  if (key !== env.TUNNEL_KEY) return new Response("forbidden", { status: 403 });

  const now = Date.now();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM tunnel_requests WHERE created_at < ?").bind(now - 120000),
    env.DB.prepare("DELETE FROM tunnel_responses WHERE created_at < ?").bind(now - 120000),
  ]);

  const n = Math.min(Math.max(parseInt(limit) || 4, 1), 8);
  const deadline = Date.now() + POLL_WAIT_MS;
  for (;;) {
    const rows = await env.DB.prepare(
      "SELECT id, method, path, headers, body FROM tunnel_requests WHERE status='pending' ORDER BY created_at ASC LIMIT ?"
    ).bind(n).all();

    if (rows.results.length > 0) {
      const ids = rows.results.map((r) => r.id);
      const placeholders = ids.map(() => "?").join(",");
      await env.DB.prepare(
        `UPDATE tunnel_requests SET status='claimed' WHERE id IN (${placeholders}) AND status='pending'`
      ).bind(...ids).run();
      return Response.json({ requests: rows.results });
    }
    if (Date.now() >= deadline) return Response.json({ requests: [] });
    await new Promise((r) => setTimeout(r, 1000));
  }
}

// Local client posts a backend response for a request id.
async function handleRespond(request, env) {
  const { key, id, status_code, headers, body } = await request.json().catch(() => ({}));
  if (key !== env.TUNNEL_KEY || !id) return new Response("forbidden", { status: 403 });

  await env.DB.prepare(
    "INSERT OR REPLACE INTO tunnel_responses (id, status_code, headers, body, created_at) VALUES (?,?,?,?,?)"
  ).bind(id, status_code | 0, JSON.stringify(headers || {}), body || null, Date.now()).run();

  return Response.json({ ok: true });
}

// Hardened public ingress.
async function handleIngress(request, env) {
  // 1. public key auth: accept X-Tunnel-Auth OR Authorization: Bearer <PUBLIC_KEY>
  //    (the latter lets standard OpenAI clients use PUBLIC_KEY as their API key;
  //     caller headers are still dropped below, backend key injected server-side)
  const pub = request.headers.get("x-tunnel-auth") || "";
  const bearer = request.headers.get("authorization") || "";
  const okAuth = (pub && pub === env.PUBLIC_KEY) ||
                 (bearer === "Bearer " + env.PUBLIC_KEY);
  if (!okAuth) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
  }

  // 2. rate limit (D1 sliding window)
  const now = Date.now();
  const cnt = await env.DB.prepare(
    "SELECT COUNT(*) AS c FROM tunnel_requests WHERE created_at > ?"
  ).bind(now - 60000).first();
  if ((cnt?.c || 0) >= RATE_LIMIT_PER_MIN) {
    return new Response(JSON.stringify({ error: "rate_limited" }), { status: 429 });
  }

  // 3. method + path allowlists
  const url = new URL(request.url);
  if (!METHOD_ALLOWLIST.has(request.method)) {
    return new Response(JSON.stringify({ error: "method not allowed" }), { status: 403 });
  }
  if (!PATH_ALLOWLIST.has(url.pathname)) {
    return new Response(JSON.stringify({ error: "path not allowed" }), { status: 403 });
  }

  // 4. header allowlist: drop everything from caller, inject backend key server-side
  const ctype = request.headers.get("content-type") || "application/json";
  const headers = {
    "content-type": ctype,
    "authorization": "Bearer " + env.BACKEND_KEY,
  };

  // 5. body cap
  let bodyB64 = null;
  let buf = null;
  if (request.body && request.method !== "GET" && request.method !== "HEAD") {
    buf = await request.arrayBuffer();
    if (buf.byteLength > MAX_BODY) {
      return new Response(JSON.stringify({ error: "body too large" }), { status: 413 });
    }
    if (buf.byteLength > 0) {
      const bytes = new Uint8Array(buf);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 32768) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
      }
      bodyB64 = btoa(bin);
    }
  }

  const id = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO tunnel_requests (id, method, path, headers, body, status, created_at) VALUES (?,?,?,?,?,'pending',?)"
  ).bind(id, request.method, url.pathname + url.search, JSON.stringify(headers), bodyB64, now).run();

  // 5b. streaming requests: replay D1 chunks as SSE instead of waiting
  // for the full response (true incremental delivery, no 25s cap).
  if (request.method === "POST" && url.pathname === "/v1/chat/completions" && buf && buf.byteLength > 0) {
    try {
      if (JSON.parse(new TextDecoder().decode(buf)).stream === true) {
        return streamChunks(id, request.signal, env);
      }
    } catch {}
  }

  // 6. wait for tunneled response
  const deadline = Date.now() + WAIT_MS;
  while (Date.now() < deadline) {
    const row = await env.DB.prepare(
      "SELECT status_code, headers, body FROM tunnel_responses WHERE id=?"
    ).bind(id).first();
    if (row) {
      await env.DB.batch([
        env.DB.prepare("DELETE FROM tunnel_requests WHERE id=?").bind(id),
        env.DB.prepare("DELETE FROM tunnel_responses WHERE id=?").bind(id),
      ]);
      const resHeaders = new Headers(JSON.parse(row.headers || "{}"));
      let body = null;
      if (row.body) {
        const bin = atob(row.body);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        body = bytes.buffer;
      }
      return new Response(body, { status: row.status_code, headers: resHeaders });
    }
    await new Promise((r) => setTimeout(r, 400));
  }

  await env.DB.prepare("DELETE FROM tunnel_requests WHERE id=?").bind(id).run();
  return new Response(JSON.stringify({ error: "tunnel timeout" }), { status: 504 });
}

// Streaming ingress: replay tunnel_chunks rows as SSE until the done marker.
// The VM client writes chunks incrementally; we long-poll D1 and push each
// batch to the caller as it arrives (true streaming, no 25s cap).
async function streamChunks(id, signal, env) {
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const enc = new TextEncoder();
  const write = (s) => writer.write(enc.encode(s));

  (async () => {
    let seq = 0;
    const deadline = Date.now() + 6 * 60 * 1000; // absolute cap
    let idleSince = Date.now();
    try {
      for (;;) {
        if (signal.aborted) break;
        const rows = await env.DB.prepare(
          "SELECT seq, data FROM tunnel_chunks WHERE req_id=? AND seq>=? ORDER BY seq ASC LIMIT 50"
        ).bind(id, seq).all();
        for (const r of rows.results || []) {
          // base64 -> bytes -> proper UTF-8 string.
          // NOTE: atob() returns a "binary string" (one char per byte); it must
          // NOT be passed through TextEncoder directly, or non-ASCII text gets
          // double-encoded into mojibake (learned the hard way, 2026-10-08).
          const bin = atob(r.data);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          const raw = new TextDecoder().decode(bytes);
          let ctrl = null;
          try {
            const j = JSON.parse(raw);
            if (j && typeof j.__ctrl__ === "string") ctrl = j;
          } catch {}
          if (ctrl && ctrl.__ctrl__ === "done") {
            await write("data: [DONE]\n\n");
            await cleanupStream(id, env);
            await writer.close();
            return;
          }
          if (ctrl && ctrl.__ctrl__ === "error") {
            await write(`data: ${JSON.stringify({ error: ctrl.message || "stream error" })}\n\n`);
            await write("data: [DONE]\n\n");
            await cleanupStream(id, env);
            await writer.close();
            return;
          }
          await write(raw);
          seq = r.seq + 1;
          idleSince = Date.now();
        }
        if (Date.now() - idleSince > 30000 || Date.now() > deadline) break;
        await new Promise((r) => setTimeout(r, 350));
      }
    } catch {}
    try { await cleanupStream(id, env); } catch {}
    try { await writer.close(); } catch {}
  })();

  return new Response(readable, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      "connection": "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}

async function cleanupStream(id, env) {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM tunnel_requests WHERE id=?").bind(id),
    env.DB.prepare("DELETE FROM tunnel_chunks WHERE req_id=?").bind(id),
  ]);
}
