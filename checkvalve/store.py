"""
Phase 3 — RAG store (SQLite catalog).

Holds every validated work instruction and its steps so future generations can
reuse expert content. At this corpus size vectors/ANN would be theater (every
query returns the whole pool), so retrieval is a plain SQL/tag filter; swap in
LanceDB + ko-sroberta once several validated docs exist.

The gold hand-authored guide is seeded as document #0 (status='validated') — its
control points are the candidate pool the author stage draws from.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import DB_PATH, PKG, PART_ID

SCHEMA = """
CREATE TABLE IF NOT EXISTS document(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  part_id TEXT NOT NULL,
  source_clip TEXT,
  status TEXT NOT NULL DEFAULT 'draft',   -- draft | validated
  meta_json TEXT, seq_json TEXT, self_json TEXT,
  origin TEXT,                            -- gold | pipeline
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS step(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  pos INTEGER, tag TEXT, at INTEGER, insp INTEGER,
  badge TEXT, text TEXT, sub TEXT, pts_json TEXT, cap TEXT,
  provenance TEXT                         -- human | rag | vision | stub
);
-- at most one gold doc per part: makes seed_gold race-safe under the threaded UI
CREATE UNIQUE INDEX IF NOT EXISTS ux_gold ON document(part_id) WHERE origin='gold';
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")     # concurrent reads/writes under ThreadingTCPServer
    con.execute("PRAGMA busy_timeout=5000")    # wait, don't error, on a transient write lock
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(document)")}   # additive migration
    if "signed_by" not in cols:
        con.execute("ALTER TABLE document ADD COLUMN signed_by TEXT")
    if "signed_at" not in cols:
        con.execute("ALTER TABLE document ADD COLUMN signed_at TEXT")
    return con


def promote_to_validated(part_id, source_clip, signed_by):
    """Approve seam: flip this clip's latest draft to validated + record the signer.
    ONE validated doc per clip: supersede (delete) any prior validated version of the
    SAME clip first, so re-approving replaces rather than stacking. Without this the RAG
    pool feeds back on itself (each approved guide was built FROM the pool) and grows
    5->10->20->40 on repeated approvals. Distinct clips still each contribute one doc."""
    con = connect()
    try:
        row = con.execute(
            "SELECT id FROM document WHERE part_id=? AND source_clip=? AND status='draft'"
            " ORDER BY id DESC LIMIT 1", (part_id, source_clip)).fetchone()
        if not row:
            # Idempotent re-approve: no draft (already promoted) but a validated doc exists
            # for this clip — just refresh the signer instead of erroring the approve.
            existing = con.execute(
                "SELECT id FROM document WHERE part_id=? AND source_clip=? AND status='validated'"
                " ORDER BY id DESC LIMIT 1", (part_id, source_clip)).fetchone()
            if existing:
                con.execute("UPDATE document SET signed_by=?, signed_at=datetime('now') WHERE id=?",
                            (signed_by, existing["id"]))
                con.commit()
                return existing["id"]
            raise ValueError("no draft to promote")
        con.execute("DELETE FROM document WHERE part_id=? AND source_clip=? AND status='validated'"
                    " AND id<>?", (part_id, source_clip, row["id"]))
        con.execute("UPDATE document SET status='validated', signed_by=?, signed_at=datetime('now')"
                    " WHERE id=?", (signed_by, row["id"]))
        con.commit()
        return row["id"]
    finally:
        con.close()


def ingest_document(part_id, source_clip, status, meta, steps, seq, self_,
                    origin="pipeline", provenance="rag") -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO document(part_id,source_clip,status,meta_json,seq_json,self_json,origin)"
            " VALUES(?,?,?,?,?,?,?)",
            (part_id, source_clip, status, json.dumps(meta, ensure_ascii=False),
             json.dumps(seq, ensure_ascii=False), json.dumps(self_, ensure_ascii=False), origin))
        doc_id = cur.lastrowid
        for i, s in enumerate(steps):
            con.execute(
                "INSERT INTO step(doc_id,pos,tag,at,insp,badge,text,sub,pts_json,cap,provenance)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, i, s.get("tag"), s.get("at"), s.get("insp"), s.get("badge"),
                 s.get("text"), s.get("sub"), json.dumps(s.get("pts", []), ensure_ascii=False),
                 s.get("cap"), s.get("provenance", provenance)))
        con.commit()
        return doc_id
    finally:
        con.close()


# NOTE: get_validated_steps / get_gold / seed_gold were removed with RAG (the API is now the
# analyst). The store is an audit log only: ingest_document (drafts), delete_drafts,
# promote_to_validated (approve seam), list_documents.


def list_documents() -> list[dict]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT d.id,d.part_id,d.source_clip,d.status,d.origin,d.created_at,"
            " (SELECT COUNT(*) FROM step s WHERE s.doc_id=d.id) n_steps"
            " FROM document d ORDER BY d.id").fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def delete_drafts(part_id, source_clip) -> None:
    """Drop prior pipeline drafts for a clip so a re-run replaces rather than
    accumulates duplicates (steps cascade via the FK)."""
    con = connect()
    try:
        con.execute("DELETE FROM document WHERE part_id=? AND source_clip=? AND status='draft'",
                    (part_id, source_clip))
        con.commit()
    finally:
        con.close()


