"""The catalogue: one record per file (or per project/package unit). Source of truth for search, views and reports."""
import os, sqlite3, json, time

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT, ext TEXT, kind TEXT, unit TEXT,
  size INTEGER, mtime REAL, birth REAL, cloud_only INTEGER DEFAULT 0, sensitive INTEGER DEFAULT 0, protected INTEGER DEFAULT 0,
  hash TEXT, date TEXT, date_source TEXT, year TEXT,
  entity TEXT, entity_type TEXT, entity_conf TEXT, entity_why TEXT, suggestions TEXT,
  doc_type TEXT, doc_conf TEXT, topic TEXT, lifecycle TEXT,
  title TEXT, pages INTEGER, snippet TEXT, tags TEXT, extra TEXT, inner_count INTEGER,
  scanned_at REAL, seen_at REAL, errors TEXT);
CREATE INDEX IF NOT EXISTS i_hash ON files(hash);
CREATE INDEX IF NOT EXISTS i_entity ON files(entity);
CREATE INDEX IF NOT EXISTS i_kind ON files(kind);
CREATE TABLE IF NOT EXISTS archive_items(file_id INTEGER, name TEXT, size INTEGER);
CREATE INDEX IF NOT EXISTS i_arch ON archive_items(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(name, path, title, body, tags, entity, doc_type, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS history(t REAL, action TEXT, path TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS decisions(path TEXT PRIMARY KEY, hash TEXT, fields TEXT, by TEXT, t REAL);
CREATE INDEX IF NOT EXISTS i_dec_hash ON decisions(hash);
CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY, t REAL, by TEXT, action TEXT, summary TEXT, n INTEGER, undo TEXT, undone REAL);
CREATE TABLE IF NOT EXISTS plan(file_id INTEGER PRIMARY KEY, path TEXT, action TEXT, target TEXT, by TEXT, t REAL);
CREATE TABLE IF NOT EXISTS sort_runs(id INTEGER PRIMARY KEY, t REAL, by TEXT, summary TEXT, log TEXT, moved INTEGER, skipped INTEGER,
  errors INTEGER, removed_dirs TEXT, undone REAL);
CREATE TABLE IF NOT EXISTS dismissed(key TEXT PRIMARY KEY, t REAL, by TEXT, until REAL);
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, display TEXT, role TEXT, scope TEXT, salt BLOB, hash BLOB, iters INTEGER,
  created REAL, last_login REAL);
"""

# Columns a person (or a rules re-run) may change. Everything else comes only from reading the file.
LABEL_COLS = ["entity", "entity_type", "entity_conf", "entity_why", "suggestions", "doc_type", "doc_conf", "topic", "lifecycle"]


def _j(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v

# Records sent by other computers (agents) live under uo://<computer>/<their path>. They are searchable here, but nothing on
# this computer ever acts on them (move, tag, read, transcribe), and a local scan never removes them.
REMOTE = "uo://"
LOCAL_SQL = "path NOT LIKE 'uo://%'"


def is_remote(path):
    return bool(path) and path.startswith(REMOTE)


COLS = ["path", "name", "ext", "kind", "unit", "size", "mtime", "birth", "cloud_only", "sensitive", "protected", "hash", "date",
        "date_source", "year", "entity", "entity_type", "entity_conf", "entity_why", "suggestions", "doc_type", "doc_conf", "topic",
        "lifecycle", "title", "pages", "snippet", "tags", "extra", "inner_count", "scanned_at", "seen_at", "errors"]


class Catalogue:
    def __init__(self, folder):
        self.folder = folder
        self.db = sqlite3.connect(os.path.join(folder, "catalogue.db"), timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def known(self):
        return {r["path"]: (r["size"], r["mtime"]) for r in self.db.execute(f"SELECT path,size,mtime FROM files WHERE scanned_at IS NOT NULL AND {LOCAL_SQL}")}

    def touch(self, paths, t):
        self.db.executemany("UPDATE files SET seen_at=? WHERE path=?", [(t, p) for p in paths])

    def save(self, recs):
        cur = self.db.cursor()
        for r in recs:
            d = self.decision_for(r["path"], r.get("hash"))
            if d:  # a person's decision always wins over the rules
                r.update(d)
            vals = []
            for c in COLS:
                v = r.get(c)
                vals.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            cur.execute(f"INSERT INTO files({','.join(COLS)}) VALUES({','.join('?' * len(COLS))}) "
                        f"ON CONFLICT(path) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in COLS[1:])}", vals)
            fid = cur.execute("SELECT id FROM files WHERE path=?", (r["path"],)).fetchone()[0]
            cur.execute("DELETE FROM fts WHERE rowid=?", (fid,))
            cur.execute("INSERT INTO fts(rowid,name,path,title,body,tags,entity,doc_type) VALUES(?,?,?,?,?,?,?,?)",
                        (fid, r.get("name"), r["path"], r.get("title") or "", r.get("text") or "", " ".join(r.get("tags") or []),
                         r.get("entity") or "", r.get("doc_type") or ""))
            cur.execute("DELETE FROM archive_items WHERE file_id=?", (fid,))
            if r.get("archive_items"):
                cur.executemany("INSERT INTO archive_items VALUES(?,?,?)", [(fid, n, s) for n, s in r["archive_items"]])
        self.db.commit()

    def forget_missing(self, t):
        n = self.db.execute(f"SELECT count(*) FROM files WHERE seen_at < ? AND {LOCAL_SQL}", (t,)).fetchone()[0]
        ids = [r[0] for r in self.db.execute(f"SELECT id FROM files WHERE seen_at < ? AND {LOCAL_SQL}", (t,))]
        for i in ids:
            self.db.execute("DELETE FROM fts WHERE rowid=?", (i,))
            self.db.execute("DELETE FROM archive_items WHERE file_id=?", (i,))
        self.db.execute(f"DELETE FROM files WHERE seen_at < ? AND {LOCAL_SQL}", (t,))
        self.db.commit()
        return n

    def set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))
        self.db.commit()

    def get_meta(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    # ---- decisions made by a person (owner / topic / document type), kept across re-scans and moves ----
    def decision_for(self, path, h=None):
        row = self.db.execute("SELECT fields FROM decisions WHERE path=?", (path,)).fetchone()
        if not row and h:
            row = self.db.execute("SELECT fields FROM decisions WHERE hash=? ORDER BY t DESC LIMIT 1", (h,)).fetchone()
        return json.loads(row[0]) if row else None

    def _cols(self, fid):
        r = self.db.execute(f"SELECT path,hash,{','.join(LABEL_COLS)} FROM files WHERE id=?", (fid,)).fetchone()
        return r

    def _write_cols(self, fid, cols):
        cols = {k: v for k, v in cols.items() if k in LABEL_COLS}
        self.db.execute(f"UPDATE files SET {','.join(k + '=?' for k in cols)} WHERE id=?", [_j(v) for v in cols.values()] + [fid])
        if "entity" in cols or "doc_type" in cols:
            r = self.db.execute("SELECT entity,doc_type FROM files WHERE id=?", (fid,)).fetchone()
            self.db.execute("UPDATE fts SET entity=?, doc_type=? WHERE rowid=?", (r[0] or "", r[1] or "", fid))

    def decide(self, ids, fields, by, summary):
        """Apply a person's labels to files. Returns the change id (for undo)."""
        undo, now = [], time.time()
        for fid in ids:
            r = self._cols(fid)
            if not r:
                continue
            old = {k: r[k] for k in LABEL_COLS}
            prev = self.db.execute("SELECT path,hash,fields,by,t FROM decisions WHERE path=?", (r["path"],)).fetchone()
            undo.append([fid, old, list(prev) if prev else None, r["path"]])
            merged = dict(json.loads(prev[2])) if prev else {}
            merged.update(fields)
            self.db.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?)", (r["path"], r["hash"], json.dumps(merged, ensure_ascii=False), by, now))
            self._write_cols(fid, fields)
        return self._log(by, "label", summary, undo)

    def relabel(self, updates, by, summary):
        """Apply rule results (from a rules re-run). updates: [(id, {col: value})]."""
        undo = []
        for fid, cols in updates:
            r = self._cols(fid)
            if r:
                undo.append([fid, {k: r[k] for k in LABEL_COLS}, "keep", r["path"]])
                self._write_cols(fid, cols)
        return self._log(by, "rules", summary, undo)

    def _log(self, by, action, summary, undo):
        cur = self.db.execute("INSERT INTO changes(t,by,action,summary,n,undo) VALUES(?,?,?,?,?,?)",
                              (time.time(), by, action, summary, len(undo), json.dumps(undo, ensure_ascii=False)))
        self.db.commit()
        return cur.lastrowid

    def undo(self, cid, by):
        row = self.db.execute("SELECT undo, undone, summary FROM changes WHERE id=?", (cid,)).fetchone()
        if not row or row[1]:
            return 0
        items = json.loads(row[0])
        for fid, old, prev, path in reversed(items):
            if self.db.execute("SELECT 1 FROM files WHERE id=?", (fid,)).fetchone():
                self._write_cols(fid, {k: (json.loads(v) if k == "suggestions" and isinstance(v, str) and v.startswith("[") else v)
                                       for k, v in old.items()})
            if prev != "keep":
                self.db.execute("DELETE FROM decisions WHERE path=?", (path,))
                if prev:
                    self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?)", prev)
        self.db.execute("UPDATE changes SET undone=? WHERE id=?", (time.time(), cid))
        self._log(by, "undo", f"Undid: {row[2]}", [])
        return len(items)

    def changes(self, limit=100):
        return [dict(r) for r in self.db.execute("SELECT id,t,by,action,summary,n,undone FROM changes ORDER BY id DESC LIMIT ?", (limit,))]
