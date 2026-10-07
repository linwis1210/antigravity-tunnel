-- Skema D1 untuk tunnel polling.
-- Jalankan sekali: wrangler d1 execute <db-name> --file=schema.sql
-- (atau --remote bila database sudah ada di Cloudflare)

CREATE TABLE IF NOT EXISTS tunnel_requests (
  id         TEXT PRIMARY KEY,
  method     TEXT,
  path       TEXT,
  headers    TEXT,
  body       TEXT,
  status     TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS tunnel_responses (
  id          TEXT PRIMARY KEY,
  status_code INTEGER,
  headers     TEXT,
  body        TEXT,
  created_at  INTEGER
);
