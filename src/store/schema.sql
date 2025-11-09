PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  unit_id       TEXT,
  doc_type      TEXT,
  version       INTEGER DEFAULT 1,
  effective_from TEXT,
  pages         INTEGER,
  size_kb       REAL,
  uploaded_at   TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  id           TEXT PRIMARY KEY,
  doc_id       TEXT NOT NULL,
  page         INTEGER,
  chunk_index  INTEGER,
  text         TEXT,
  hash         TEXT,
  created_at   TEXT,
  FOREIGN KEY (doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS tickets (
  id            TEXT PRIMARY KEY,
  unit_id       TEXT NOT NULL,
  category      TEXT NOT NULL,
  priority      TEXT NOT NULL,
  status        TEXT NOT NULL,
  summary       TEXT NOT NULL,
  reporter      TEXT,
  access_window TEXT,
  assignee      TEXT,
  eta           TEXT,
  hazard_flag   INTEGER DEFAULT 0,
  created_at    TEXT,
  updated_at    TEXT,
  closed_at     TEXT
);

