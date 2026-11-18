"""Accounts for the local page. Stored inside the encrypted catalogue. Passwords are never stored, only a slow
salted hash (PBKDF2-SHA256). Roles: 'admin' sees and changes everything; 'member' sees only the owners listed in
their scope, never sensitive files, and cannot change anything."""
import os, re, json, time, hmac, hashlib, secrets

ITERS = 600_000
USER_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


class AuthError(Exception):
    pass


def _hash(pw, salt, iters=ITERS):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iters)


class Auth:
    def __init__(self, cat, idle_hours=4):
        self.cat, self.idle = cat, idle_hours * 3600
        self.sessions, self.fails = {}, {}

    # ---- accounts ----
    def has_users(self):
        return self.cat.db.execute("SELECT count(*) FROM users").fetchone()[0] > 0

    def list(self):
        out = []
        for r in self.cat.db.execute("SELECT username,display,role,scope,created,last_login FROM users ORDER BY role, username"):
            d = dict(r); d["scope"] = json.loads(d["scope"] or "[]"); out.append(d)
        return out

    def get_user(self, username):
        r = self.cat.db.execute("SELECT username,display,role,scope FROM users WHERE username=?", (username,)).fetchone()
        if not r:
            return None
        d = dict(r); d["scope"] = json.loads(d["scope"] or "[]")
        return d

    @staticmethod
    def check_password(pw):
        if len(pw or "") < 8:
            raise AuthError("Password must be at least 8 characters.")

    def add(self, username, display, role, scope, pw):
        username = (username or "").strip().lower()
        if not USER_RX.match(username):
            raise AuthError("User name: 2–32 characters, letters, digits, dot, dash or underscore.")
        if role not in ("admin", "member"):
            raise AuthError("Role must be admin or member.")
        if self.get_user(username):
            raise AuthError("That user name is taken.")
        self.check_password(pw)
        salt = secrets.token_bytes(16)
        self.cat.db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?,NULL)",
                            (username, display or username, role, json.dumps(scope or [], ensure_ascii=False), salt, _hash(pw, salt), ITERS, time.time()))
        self.cat.db.commit()

    def update(self, username, display=None, role=None, scope=None, pw=None):
        u = self.get_user(username)
        if not u:
            raise AuthError("No such user.")
        if role and role != u["role"] and u["role"] == "admin" and self._admins() == 1:
            raise AuthError("This is the only admin; make another admin first.")
        if display is not None:
            self.cat.db.execute("UPDATE users SET display=? WHERE username=?", (display or username, username))
        if role in ("admin", "member"):
            self.cat.db.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        if scope is not None:
            self.cat.db.execute("UPDATE users SET scope=? WHERE username=?", (json.dumps(scope, ensure_ascii=False), username))
        if pw:
            self.check_password(pw)
            salt = secrets.token_bytes(16)
            self.cat.db.execute("UPDATE users SET salt=?, hash=?, iters=? WHERE username=?", (salt, _hash(pw, salt), ITERS, username))
            self.end_sessions(username)
        self.cat.db.commit()

    def remove(self, username):
        u = self.get_user(username)
        if not u:
            raise AuthError("No such user.")
        if u["role"] == "admin" and self._admins() == 1:
            raise AuthError("This is the only admin and cannot be removed.")
        self.cat.db.execute("DELETE FROM users WHERE username=?", (username,))
        self.cat.db.commit()
        self.end_sessions(username)

    def _admins(self):
        return self.cat.db.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0]

    # ---- sign in ----
    def login(self, username, pw):
        username = (username or "").strip().lower()
        n, until = self.fails.get(username, (0, 0))
        if time.time() < until:
            raise AuthError(f"Too many attempts. Try again in {int(until - time.time()) + 1} s.")
        r = self.cat.db.execute("SELECT salt,hash,iters FROM users WHERE username=?", (username,)).fetchone()
        ok = bool(r) and hmac.compare_digest(_hash(pw or "", r[0], r[2]), r[1])
        if not r:
            _hash(pw or "", b"0" * 16)  # same cost whether or not the user exists
        if not ok:
            n += 1
            self.fails[username] = (n, time.time() + (min(60 * 2 ** (n - 5), 3600) if n >= 5 else 0))
            raise AuthError("Wrong user name or password.")
        self.fails.pop(username, None)
        self.cat.db.execute("UPDATE users SET last_login=? WHERE username=?", (time.time(), username))
        self.cat.db.commit()
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = {"user": username, "seen": time.time()}
        return sid

    def session(self, sid):
        s = self.sessions.get(sid or "")
        if not s:
            return None
        if time.time() - s["seen"] > self.idle:
            self.sessions.pop(sid, None); return None
        u = self.get_user(s["user"])
        if not u:
            self.sessions.pop(sid, None); return None
        s["seen"] = time.time()
        return u

    def logout(self, sid):
        self.sessions.pop(sid or "", None)

    def end_sessions(self, username):
        for k in [k for k, v in self.sessions.items() if v["user"] == username]:
            self.sessions.pop(k, None)
