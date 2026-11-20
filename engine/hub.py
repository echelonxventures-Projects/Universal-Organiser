"""Hub side of "one search for every computer at home".

A hub is an ordinary install that also accepts catalogue records from paired computers (agents). Files never move:
an agent sends only what its own scan learnt (name, size, dates, owner/topic labels, text it read), and the hub keeps
those records under  uo://<computer>/<path on that computer>  so they are searchable but never acted on here.

Pairing: an admin makes a one-time code on the hub (valid 15 minutes). The agent sends that code once and gets a long
random token; the hub keeps only the token's SHA-256. Removing a computer deletes its token and every record it sent.
"""
import hashlib, json, re, secrets, time

from .catalogue import COLS, REMOTE

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY, name TEXT UNIQUE, os TEXT, version TEXT, token_hash TEXT,
  created REAL, last_seen REAL, last_sync REAL, files INTEGER DEFAULT 0, ip TEXT);
CREATE TABLE IF NOT EXISTS pair_codes(code TEXT PRIMARY KEY, created REAL, expires REAL, by TEXT);
"""
CODE_MINUTES = 15
# what an agent may send; everything else in a record is ignored
FIELDS = [c for c in COLS if c not in ("path", "scanned_at", "seen_at", "protected")] + ["text"]
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def remote_path(machine, path):
    return f"{REMOTE}{machine}/{path.lstrip('/')}"


class Hub:
    def __init__(self, cat):
        self.cat = cat
        cat.db.executescript(SCHEMA)
        cat.db.commit()

    # ---------------------------------------------------------------- pairing (admin on the hub)
    def new_code(self, by):
        self.cat.db.execute("DELETE FROM pair_codes WHERE expires < ?", (time.time(),))
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        now = time.time()
        self.cat.db.execute("INSERT INTO pair_codes VALUES(?,?,?,?)", (code, now, now + CODE_MINUTES * 60, by))
        self.cat.db.commit()
        return {"code": f"{code[:4]}-{code[4:]}", "expires": now + CODE_MINUTES * 60}

    def pair(self, code, name, os_name, version, ip):
        code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
        row = self.cat.db.execute("SELECT expires FROM pair_codes WHERE code=?", (code,)).fetchone()
        if not row or row[0] < time.time():
            raise ValueError("That pairing code is wrong or has expired. Make a new one on the hub (Computers page).")
        name = str(name or "").strip()
        if not NAME_RX.match(name):
            raise ValueError("Computer name: 1-40 letters, digits, space, dot, dash or underscore.")
        if self.cat.db.execute("SELECT 1 FROM machines WHERE lower(name)=lower(?)", (name,)).fetchone():
            raise ValueError(f"A computer called “{name}” is already paired. Remove it on the hub first, or choose another name.")
        token, mid = secrets.token_urlsafe(32), secrets.token_hex(8)
        self.cat.db.execute("DELETE FROM pair_codes WHERE code=?", (code,))
        self.cat.db.execute("INSERT INTO machines(id,name,os,version,token_hash,created,last_seen,ip) VALUES(?,?,?,?,?,?,?,?)",
                            (mid, name, str(os_name)[:20], str(version)[:20], _h(token), time.time(), time.time(), ip))
        self.cat.db.commit()
        return {"machine": mid, "name": name, "token": token}

    def machine_for(self, token, ip=None):
        if not token:
            return None
        r = self.cat.db.execute("SELECT * FROM machines WHERE token_hash=?", (_h(token),)).fetchone()
        if r:
            self.cat.db.execute("UPDATE machines SET last_seen=?, ip=? WHERE id=?", (time.time(), ip, r["id"]))
        return dict(r) if r else None

    def list(self):
        return [dict(r) for r in self.cat.db.execute("SELECT id,name,os,version,created,last_seen,last_sync,files,ip FROM machines ORDER BY name")]

    def remove(self, mid):
        r = self.cat.db.execute("SELECT name FROM machines WHERE id=?", (mid,)).fetchone()
        if not r:
            return 0
        pre = remote_path(r[0], "")
        ids = [x[0] for x in self.cat.db.execute("SELECT id FROM files WHERE substr(path,1,?)=?", (len(pre), pre))]
        self._delete_ids(ids)
        self.cat.db.execute("DELETE FROM machines WHERE id=?", (mid,))
        self.cat.db.commit()
        return len(ids)

    # ---------------------------------------------------------------- records from an agent
    def _delete_ids(self, ids):
        for i in ids:
            self.cat.db.execute("DELETE FROM fts WHERE rowid=?", (i,))
            self.cat.db.execute("DELETE FROM archive_items WHERE file_id=?", (i,))
            self.cat.db.execute("DELETE FROM files WHERE id=?", (i,))

    def begin(self, m, version=None):
        if version and str(version)[:20] != m.get("version"):  # it updated itself: keep the list current
            self.cat.db.execute("UPDATE machines SET version=? WHERE id=?", (str(version)[:20], m["id"]))
            self.cat.db.commit()
        return {"sync": time.time()}

    def push(self, m, sync, records):
        """Store a batch. Each record keeps the agent's labels; a decision made on the hub for that path still wins."""
        if not isinstance(records, list) or len(records) > 2000:
            raise ValueError("records: a list of at most 2000")
        out = []
        for r in records:
            if not isinstance(r, dict) or not isinstance(r.get("path"), str) or not r["path"]:
                continue
            rec = {k: r.get(k) for k in FIELDS}
            rec["path"] = remote_path(m["name"], r["path"])
            rec["protected"] = 1  # never moved or changed from here
            rec["scanned_at"] = float(r.get("scanned_at") or sync)
            rec["seen_at"] = float(sync)
            if rec.get("sensitive"):
                rec["text"], rec["snippet"] = "", None  # agents do not send it either; belt and braces
            if isinstance(rec.get("text"), str) and len(rec["text"]) > 400_000:
                rec["text"] = rec["text"][:400_000]
            out.append(rec)
        self.cat.save(out)
        return {"stored": len(out)}

    def end(self, m, sync, paths):
        """The agent's full list of current paths: everything of that computer not in it is removed."""
        pre = remote_path(m["name"], "")
        keep = {remote_path(m["name"], p) for p in paths if isinstance(p, str)}
        rows = self.cat.db.execute("SELECT id, path FROM files WHERE substr(path,1,?)=?", (len(pre), pre)).fetchall()
        gone = [r[0] for r in rows if r[1] not in keep]
        self._delete_ids(gone)
        self.cat.db.executemany("UPDATE files SET seen_at=? WHERE path=?", [(float(sync), p) for p in keep])
        n = len(rows) - len(gone)
        self.cat.db.execute("UPDATE machines SET last_sync=?, files=? WHERE id=?", (time.time(), n, m["id"]))
        self.cat.db.commit()
        return {"files": n, "removed": len(gone)}


def load_body(raw, encoding):
    """Agent requests may be gzip-compressed JSON (large path lists)."""
    if encoding == "gzip":
        import zlib
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = d.decompress(raw, MAX_JSON)
        if d.unconsumed_tail:
            raise ValueError("too large")
    return json.loads(raw or b"{}")


MAX_BODY = 32_000_000   # bytes on the wire for one agent request
MAX_JSON = 200_000_000  # after decompression
