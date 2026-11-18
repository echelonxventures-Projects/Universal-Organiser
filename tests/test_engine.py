"""Tests that run on macOS, Windows and Linux with the standard library only:  python -m unittest discover -s tests -v

Every test uses its own throwaway data folder (UO_DATA) with a plain, unencrypted catalogue, so nothing touches a real
install, its Keychain key or its files.
"""
import http.cookiejar, json, os, re, shutil, socket, subprocess, sys, tempfile, time, unittest, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
CLI = [sys.executable, "-I", os.path.join(ROOT, "engine", "cli.py")]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Install:
    """A throwaway install: its own data folder, folders to scan and port."""

    def __init__(self, name, role="standalone", preset="personal", region="none"):
        self.dir = tempfile.mkdtemp(prefix=f"uo-{name}-")
        self.data = os.path.join(self.dir, "data")
        self.files = os.path.join(self.dir, "files")
        os.makedirs(self.files)
        self.port = free_port()
        self.env = dict(os.environ, UO_DATA=self.data, PYTHONIOENCODING="utf-8")
        sys.path.insert(0, ROOT)
        os.environ["UO_DATA"] = self.data
        from engine import setup as SU  # noqa
        import importlib, engine.config, engine.setup
        importlib.reload(engine.config); importlib.reload(engine.setup)
        m = engine.setup.build_profile({"preset": preset, "region": region, "roots": [self.files], "role": role,
                                        "library": os.path.join(self.files, "Organized"), "you": "Alex Example",
                                        "access": "local"})
        m["catalogue"] = {"encrypted": False, "allow_unencrypted_disk": True}
        m["ui"] = {"port": self.port, "lan": {"enabled": False, "port": free_port()}}
        m["plugins"] = {"transcribe": {"enabled": False}, "near_duplicate_photos": {"enabled": False}}
        os.makedirs(os.path.join(self.data, "profiles"))
        json.dump(m, open(os.path.join(self.data, "profiles", "machine.json"), "w"), indent=2)
        self.proc = None

    def write(self, rel, text):
        p = os.path.join(self.files, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
        t = time.time() - 5
        os.utime(p, (t, t))
        return p

    def uo(self, *args, check=True, input=None):
        r = subprocess.run(CLI + list(args), env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600, input=input)
        if check and r.returncode:
            raise AssertionError(f"uo {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout + r.stderr

    def serve(self):
        self.proc = subprocess.Popen(CLI + ["serve", "--no-browser"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace")
        url = None
        t0 = time.time()
        while time.time() - t0 < 60:
            line = self.proc.stdout.readline()
            m = re.search(r"(http://127\.0\.0\.1:\d+/login\S*)", line)
            if m:
                url = m[1]; break
        assert url, "server did not start"
        self.base = f"http://127.0.0.1:{self.port}"
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        return url

    def api(self, path, body=None, headers=None, ok=True):
        h = {"X-FE": "1", "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h,
                                     method="GET" if body is None else "POST")
        try:
            with self.op.open(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if ok:
                raise AssertionError(f"{path}: HTTP {e.code} {e.read()[:300]}")
            return {"_status": e.code, **json.loads(e.read() or b"{}")}

    def admin(self, url):
        t = re.search(r"t=([\w-]+)", url)[1]
        self.api("/api/setup", {"t": t, "username": "admin", "display": "Admin", "password": "correct horse 1", "password2": "correct horse 1"})

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc.stdout.close()

    def cleanup(self):
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


class Profiles(unittest.TestCase):
    def test_regions_and_presets(self):
        from engine import config, setup
        base = json.load(open(os.path.join(ROOT, "profiles", "base.json"), encoding="utf-8"))
        names = [d["name"] for d in base["doc_types"]]
        self.assertNotIn("Aadhaar", names, "country documents belong in a region pack")
        india = config.apply_region(base, "india")
        n2 = [d["name"] for d in india["doc_types"]]
        self.assertEqual(n2[:3], ["PAN card", "Aadhaar", "Passport"])
        self.assertEqual(india["insights"]["year_start_month"], 4)
        for p in setup.presets():
            m = setup.build_profile({"preset": p["id"], "roots": ["{HOME}/Documents"]})
            self.assertTrue(m["setup_done"])
        with self.assertRaises(ValueError):
            setup.build_profile({"preset": "nope", "roots": ["x"]})
        with self.assertRaises(ValueError):
            setup.build_profile({"preset": "personal", "roots": []})

    def test_no_personal_data_shipped(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "privacy_check.py"), "--all"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class EndToEnd(unittest.TestCase):
    def test_hub_and_agent(self):
        hub, ag = Install("hub", role="hub"), Install("agent", role="agent")
        try:
            hub.write("Papers/hub-invoice.txt", "Invoice number 4711 for garden work")
            hub.uo("scan")
            url = hub.serve()
            hub.admin(url)
            w = hub.api("/api/welcome")
            self.assertTrue(w["setup_done"])
            self.assertTrue(any(c["id"] == "python" for c in w["checks"]))
            # agent endpoints refuse a wrong code and a missing token
            self.assertEqual(hub.api("/api/agent/pair", {"code": "WRONG-CODE", "name": "x"}, ok=False)["_status"], 400)
            self.assertEqual(hub.api("/api/agent/begin", {}, ok=False)["_status"], 401)
            code = hub.api("/api/hub/code", {})["code"]
            ag.write("Letters/agent-letter.txt", "A letter about the zebra crossing near the school")
            ag.write("Letters/old.txt", "an obsolete note about pelicans")
            ag.uo("scan")
            out = ag.uo("agent", "pair", hub.base, code, "--name", "Study PC")
            self.assertIn("Paired", out)
            out = ag.uo("agent", "sync")
            self.assertIn("sync done", out)
            r = hub.api("/api/search?q=zebra")
            paths = [x["path"] for x in r["results"]]
            self.assertTrue(any(p.startswith("uo://Study PC/") for p in paths), paths)
            # the code works only once
            self.assertEqual(hub.api("/api/agent/pair", {"code": code, "name": "Other"}, ok=False)["_status"], 400)
            # a local scan on the hub keeps the agent's records
            hub.uo("scan")
            self.assertTrue(hub.api("/api/search?q=zebra")["results"])
            # a file removed on the agent disappears from the hub after the next sync
            os.remove(os.path.join(ag.files, "Letters", "old.txt"))
            ag.uo("scan")  # scan also syncs when paired
            self.assertFalse(hub.api("/api/search?q=pelicans")["results"])
            self.assertTrue(hub.api("/api/search?q=zebra")["results"])
            # the hub never moves a file of another computer
            fid = hub.api("/api/search?q=zebra")["results"][0]["id"]
            r = hub.api("/api/move", {"ids": [fid], "dest": os.path.join(hub.files, "Organized")}, ok=False)
            self.assertIn("another computer", json.dumps(r))
            ms = hub.api("/api/hub")["machines"]
            self.assertEqual([m["name"] for m in ms], ["Study PC"])
            removed = hub.api("/api/hub/remove", {"id": ms[0]["id"]})["removed"]
            self.assertGreaterEqual(removed, 1)
            self.assertFalse(hub.api("/api/search?q=zebra")["results"])
            self.assertIn("not paired", ag.uo("agent", "sync", check=False))
        finally:
            hub.cleanup(); ag.cleanup()

    def test_wizard_on_new_install(self):
        a = Install("new")
        try:
            os.remove(os.path.join(a.data, "profiles", "machine.json"))
            prof = {"catalogue": {"encrypted": False, "allow_unencrypted_disk": True}, "ui": {"port": a.port}}
            json.dump(prof, open(os.path.join(a.data, "profiles", "machine.json"), "w"))
            a.write("Docs/note.txt", "Insurance policy premium receipt")
            url = a.serve()
            a.admin(url)
            w = a.api("/api/welcome")
            self.assertFalse(w["setup_done"])
            self.assertGreaterEqual(len(w["presets"]), 5)
            r = a.api("/api/welcome/save", {"preset": "family", "region": "india", "roots": [a.files], "you": "Alex Example",
                                             "people": [{"name": "Sam Example", "type": "Family"}], "role": "standalone", "access": "local"})
            self.assertTrue(r["ok"])
            m = json.load(open(os.path.join(a.data, "profiles", "machine.json")))
            self.assertEqual(m["region"], "india")
            self.assertFalse(m["catalogue"]["encrypted"], "settings the wizard does not ask about are kept")
            self.assertEqual([e["name"] for e in m["entities"]], ["Alex Example", "Sam Example"])
            a.api("/api/scan/start", {})
            for _ in range(120):
                if (a.api("/api/scan/status")["job"] or {}).get("phase") in ("done", "failed"):
                    break
                time.sleep(0.5)
            self.assertEqual(a.api("/api/scan/status")["job"]["phase"], "done")
            self.assertTrue(a.api("/api/search?q=premium")["results"])
            # a family member's account can look, never change
            a.api("/api/users/add", {"username": "sam", "display": "Sam", "role": "member", "scope": ["Sam Example"], "password": "member pass 1"})
            a.api("/api/logout", {})
            a.api("/api/login", {"username": "sam", "password": "member pass 1"})
            for p in ("/api/projects/stop", "/api/projects/refresh", "/api/projects/resume", "/api/label", "/api/move", "/api/sort/run",
                      "/api/settings/save", "/api/users/add", "/api/hub/code", "/api/access", "/api/welcome/save", "/api/scan/start"):
                self.assertEqual(a.api(p, {}, ok=False).get("_status"), 403, p)
            self.assertEqual(a.api("/api/welcome", ok=False).get("_status"), 403)
        finally:
            a.cleanup()

    def test_doctor_and_package(self):
        a = Install("doc")
        try:
            out = a.uo("doctor", check=False)
            self.assertIn("Python", out)
            out = a.uo("package")
            z = re.search(r"Program package: (\S+\.zip)", out)[1]
            import zipfile
            names = zipfile.ZipFile(z).namelist()
            self.assertTrue(any(n.endswith("engine/cli.py") for n in names))
            self.assertFalse([n for n in names if n.endswith(("machine.json", "catalogue.db", ".jsonl", ".key", ".crt")) or "/logs/" in n or "/vault/" in n or ".sparsebundle" in n])
        finally:
            a.cleanup()


if __name__ == "__main__":
    unittest.main()
