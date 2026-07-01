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
    Validated docs survive delete_drafts, so the RAG pool grows (feedback loop)."""
    con = connect()
    try:
        row = con.execute(
            "SELECT id FROM document WHERE part_id=? AND source_clip=? AND status='draft'"
            " ORDER BY id DESC LIMIT 1", (part_id, source_clip)).fetchone()
        if not row:
            raise ValueError("no draft to promote")
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


def get_validated_steps(part_id=PART_ID) -> list[dict]:
    """The candidate pool: validated steps for a part, ordered by their `at`."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT s.* FROM step s JOIN document d ON d.id=s.doc_id"
            " WHERE d.part_id=? AND d.status='validated' ORDER BY s.at, s.pos", (part_id,)).fetchall()
    finally:
        con.close()
    return [{"tag": r["tag"], "at": r["at"], "insp": r["insp"], "badge": r["badge"],
             "text": r["text"], "sub": r["sub"], "pts": json.loads(r["pts_json"] or "[]"),
             "cap": r["cap"]} for r in rows]


def get_gold(part_id=PART_ID) -> dict | None:
    con = connect()
    try:
        d = con.execute("SELECT * FROM document WHERE part_id=? AND status='validated'"
                        " ORDER BY id LIMIT 1", (part_id,)).fetchone()
    finally:
        con.close()
    if not d:
        return None
    return {"id": d["id"], "meta": json.loads(d["meta_json"] or "{}"),
            "seq": json.loads(d["seq_json"] or "[]"), "self": json.loads(d["self_json"] or "[]"),
            "source_clip": d["source_clip"]}


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


def seed_gold() -> int | None:
    """Ingest gold_seed.json as validated document #0 if not already present.
    Race-safe: the ux_gold partial-unique index rejects a concurrent second
    insert, which we swallow."""
    if get_gold():
        return None
    gold = json.loads((PKG / "gold_seed.json").read_text(encoding="utf-8"))
    steps = [{**s, "provenance": "human"} for s in gold["steps"]]
    try:
        return ingest_document(gold["part_id"], gold["source_clip"], "validated",
                               gold["meta"], steps, gold["seq"], gold["self"],
                               origin="gold", provenance="human")
    except sqlite3.IntegrityError:
        return None  # another thread seeded it first
