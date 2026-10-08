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

-- Streaming chunks: written incrementally by tunnel_d1_client.py for
-- requests with "stream": true, consumed by the Worker which replays them
-- as SSE. A control row {"__ctrl__":"done"} (or "error") ends the stream.
CREATE TABLE IF NOT EXISTS tunnel_chunks (
  req_id     TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  data       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (req_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_chunks_req ON tunnel_chunks(req_id, seq);
