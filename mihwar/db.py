"""SQLite storage. One connection guarded by a re-entrant lock (FastAPI's threadpool
and the scenario thread share it). JSON columns are stored as UTF-8 text."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT, city TEXT, phone TEXT, email TEXT
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT, role TEXT NOT NULL, title_ar TEXT,
  discipline TEXT, initials TEXT, is_licensed INTEGER DEFAULT 0, license_no TEXT,
  client_id INTEGER, default_for_role INTEGER DEFAULT 0, capacity_hours_week REAL DEFAULT 40
);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  original_text TEXT, brief_json TEXT, missing_json TEXT, questions_json TEXT, complete INTEGER DEFAULT 0,
  proposal_id INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, sender TEXT NOT NULL, agent TEXT, text TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY, code TEXT, request_id INTEGER, client_id INTEGER NOT NULL, project_id INTEGER,
  status TEXT NOT NULL, title_ar TEXT, brief_json TEXT, bua_m2 REAL, lines_json TEXT, subtotal REAL,
  vat_rate REAL, vat REAL, total REAL, milestones_json TEXT, validity_days INTEGER, valid_until TEXT,
  exclusions_json TEXT, assumptions_json TEXT, history_json TEXT, created_at TEXT, approved_by INTEGER,
  approved_at TEXT, sent_at TEXT, accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, code TEXT, name_ar TEXT, name_en TEXT, client_id INTEGER, type TEXT, city TEXT,
  district TEXT, status TEXT, start_date TEXT, end_date TEXT, land_area_m2 REAL, floors INTEGER,
  bua_m2 REAL, description_ar TEXT, params_json TEXT, services_json TEXT, proposal_id INTEGER,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, seq INTEGER, tkey TEXT, phase TEXT, phase_name_ar TEXT,
  name_ar TEXT, discipline TEXT, start TEXT, end TEXT, duration_days INTEGER, hours REAL,
  depends_json TEXT, assignee_id INTEGER, status TEXT, progress INTEGER DEFAULT 0, is_milestone INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, code TEXT, title TEXT, base_key TEXT, filename TEXT,
  discipline TEXT, doc_type TEXT, number INTEGER, level TEXT, revision TEXT, rev_seq INTEGER, state TEXT,
  size_bytes INTEGER, uploaded_by INTEGER, uploaded_at TEXT, qa_status TEXT, superseded_by INTEGER,
  sha256 TEXT, stored_path TEXT
);
CREATE TABLE IF NOT EXISTS transmittals (
  id INTEGER PRIMARY KEY, code TEXT, project_id INTEGER, purpose_ar TEXT, docs_json TEXT, issued_to INTEGER,
  created_by INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS qa_reports (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, document_id INTEGER, phase TEXT, status TEXT,
  summary_ar TEXT, issues_json TEXT, checks_total INTEGER, checks_passed INTEGER, deliverables_json TEXT,
  created_at TEXT, signed_off_by INTEGER, signed_off_at TEXT, signoff_note TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, kind TEXT, title_ar TEXT, period_start TEXT,
  period_end TEXT, progress_pct INTEGER, body_ar TEXT, sections_json TEXT, sent_to_client INTEGER DEFAULT 0,
  sent_at TEXT, created_at TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts TEXT, actor_id INTEGER, action TEXT, resource TEXT, decision TEXT,
  reason_ar TEXT, run_id TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, ts TEXT, severity TEXT, type TEXT, message_ar TEXT, actor_id INTEGER,
  resource TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, event TEXT, actor_id INTEGER, status TEXT, started_at TEXT, duration_ms REAL,
  emitted_json TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY, run_id TEXT, seq INTEGER, agent TEXT, event TEXT, status TEXT, mode TEXT,
  duration_ms REAL, input_summary TEXT, output_summary TEXT, ts TEXT, input_json TEXT, output_json TEXT
);
CREATE TABLE IF NOT EXISTS selftests (
  agent TEXT PRIMARY KEY, passed INTEGER, at TEXT, checks_passed INTEGER, checks_total INTEGER
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_docs_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit(actor_id, ts);
"""

JSON_SUFFIX = "_json"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA foreign_keys=OFF")
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)

    # basic access -----------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(params))

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self.lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return row[0] if row else None

    @staticmethod
    def _encode(data: dict) -> dict:
        out = {}
        for k, v in data.items():
            if k.endswith(JSON_SUFFIX) and not isinstance(v, str) and v is not None:
                v = dumps(v)
            elif isinstance(v, bool):
                v = int(v)
            out[k] = v
        return out

    def insert(self, table: str, data: dict) -> int:
        data = self._encode(data)
        cols = ", ".join(data.keys())
        marks = ", ".join("?" for _ in data)
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
            return int(cur.lastrowid)

    def update(self, table: str, row_id: Any, data: dict, key: str = "id") -> None:
        if not data:
            return
        data = self._encode(data)
        sets = ", ".join(f"{k} = ?" for k in data)
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", (*data.values(), row_id))

    def get(self, table: str, row_id: Any, key: str = "id") -> dict | None:
        return self.one(f"SELECT * FROM {table} WHERE {key} = ?", (row_id,))

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def reset(self) -> None:
        with self.lock:
            tables = [r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t in tables:
                self.conn.execute(f"DELETE FROM {t}")

    def close(self) -> None:
        with self.lock:
            self.conn.close()
