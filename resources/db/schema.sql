-- Personal Super Assistant SQLite schema
-- Database: SQLite3 | Charset: UTF-8 | IDs: UUID TEXT

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whitelist_roots (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  root_paths_json TEXT,
  instructions TEXT,
  expert_id TEXT,
  skill_ids_json TEXT,
  mcp_ids_json TEXT,
  knowledge_ids_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key TEXT,
  model TEXT NOT NULL,
  temperature REAL NOT NULL DEFAULT 0.7,
  max_tokens INTEGER NOT NULL DEFAULT 2048,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  system_prompt TEXT NOT NULL,
  model_profile_id TEXT,
  skill_ids_json TEXT,
  mcp_ids_json TEXT,
  knowledge_ids_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  summary_text TEXT,
  summary_upto_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS session_attachments (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  mime_type TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_attachments_session ON session_attachments(session_id, created_at);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT,
  reasoning_content TEXT,
  tool_calls_json TEXT,
  tool_call_id TEXT,
  parent_message_id TEXT,
  status TEXT NOT NULL DEFAULT 'complete',
  token_estimate INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS chat_runs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  error_message TEXT,
  pending_json TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  triggers_json TEXT,
  permissions_json TEXT,
  skill_path TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  version TEXT,
  category TEXT,
  source TEXT,
  platforms_json TEXT,
  metadata_json TEXT,
  content_hash TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_bundles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  skills_json TEXT NOT NULL,
  instruction TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_skill_writes (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  action TEXT NOT NULL,
  diff_text TEXT,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hermes_toolset_settings (
  id TEXT PRIMARY KEY,
  toolset TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_servers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  transport TEXT NOT NULL,
  command TEXT,
  args_json TEXT,
  env_json TEXT,
  url TEXT,
  headers_json TEXT,
  tools_policy_json TEXT,
  timeout INTEGER,
  connect_timeout INTEGER,
  supports_parallel INTEGER NOT NULL DEFAULT 0,
  auth_type TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_tools_cache (
  id TEXT PRIMARY KEY,
  server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  input_schema_json TEXT,
  discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  type TEXT NOT NULL,
  content TEXT NOT NULL,
  tags_json TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  source_session_id TEXT,
  confidence REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_ws ON memories(workspace_id, type, pinned);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content,
  content='memories',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  description TEXT,
  root_path TEXT NOT NULL,
  doc_count INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'idle',
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_bases_ws ON knowledge_bases(workspace_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_sources (
  id TEXT PRIMARY KEY,
  base_id TEXT REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  name TEXT,
  path TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'path',
  state TEXT NOT NULL DEFAULT 'idle',
  doc_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  content_hash TEXT,
  mtime TEXT,
  indexed_at TEXT,
  UNIQUE(source_id, path)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  token_estimate INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
  content,
  content='knowledge_chunks',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content)
    VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE OF content ON knowledge_chunks BEGIN
  INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content)
    VALUES('delete', old.rowid, old.content);
  INSERT INTO knowledge_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS tool_call_audits (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  run_id TEXT REFERENCES chat_runs(id) ON DELETE SET NULL,
  tool_call_id TEXT,
  name TEXT NOT NULL,
  source TEXT,
  arguments_json TEXT,
  result_json TEXT,
  is_error INTEGER NOT NULL DEFAULT 0,
  risk TEXT,
  confirm_status TEXT,
  duration_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_session ON tool_call_audits(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_name ON tool_call_audits(name, created_at);

CREATE TABLE IF NOT EXISTS checklists (
  id TEXT PRIMARY KEY,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  source_message_id TEXT,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_items (
  id TEXT PRIMARY KEY,
  checklist_id TEXT NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  prompt TEXT NOT NULL,
  schedule_raw TEXT NOT NULL,
  schedule_kind TEXT NOT NULL,
  interval_seconds INTEGER,
  next_run_at TEXT,
  repeat_mode TEXT NOT NULL DEFAULT 'forever',
  repeat_limit INTEGER,
  repeat_done INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL DEFAULT 'active',
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  model_profile_id TEXT,
  expert_id TEXT,
  knowledge_ids_json TEXT,
  skill_ids_json TEXT,
  mcp_ids_json TEXT,
  delivery_mode TEXT NOT NULL DEFAULT 'new_session',
  target_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  last_run_at TEXT,
  last_status TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run
  ON scheduled_jobs(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS scheduled_job_runs (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  run_id TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  output_preview TEXT,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job
  ON scheduled_job_runs(job_id, started_at DESC);
