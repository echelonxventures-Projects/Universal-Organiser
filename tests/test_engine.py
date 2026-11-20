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


class NamesOnly(unittest.TestCase):
    """A disk without encryption (or catalogue.text = names): file names and labels are searchable, the documents'
    text is never kept; switching back to full text and a full scan brings it back."""

    def test_names_only_then_full(self):
        inst = Install("names")
        try:
            prof = os.path.join(inst.data, "profiles", "machine.json")
            with open(prof) as f:
                m = json.load(f)
            m["catalogue"]["text"] = "names"
            with open(prof, "w") as f:
                json.dump(m, f)
            inst.write("Notes/garden-plan.txt", "The quokkafern grows by the shed")
            out = inst.uo("scan")
            self.assertIn("Names only", out)
            self.assertIn("garden-plan.txt", inst.uo("search", "garden"))
            self.assertNotIn("garden-plan.txt", inst.uo("search", "quokkafern"), "text inside files is not kept")
            import sqlite3
            db = sqlite3.connect(os.path.join(inst.data, "catalogue", "catalogue.db")) if os.path.exists(
                os.path.join(inst.data, "catalogue", "catalogue.db")) else None
            if db:
                self.assertEqual(db.execute("SELECT count(*) FROM fts WHERE body != ''").fetchone()[0], 0)
                db.close()
            m["catalogue"]["text"] = "full"
            with open(prof, "w") as f:
                json.dump(m, f)
            self.assertIn("Full text is on again", inst.uo("scan", "--full"))
            self.assertIn("garden-plan.txt", inst.uo("search", "quokkafern"))
        finally:
            shutil.rmtree(inst.dir, ignore_errors=True)


class ProblemReport(unittest.TestCase):
    def test_nothing_personal(self):
        sys.path.insert(0, ROOT)
        from engine.report import redact
        t = redact("scan failed: /Users/sam/Tax 2025/Form 16 Sam.pdf: unreadable\n"
                   r"error C:\Users\Asha\Desktop\passport scan.jpg not found" "\n"
                   "hub https://study.local:8766 mail sam@example.com account 1234 5678 9012 moved “Asha” here")
        for bad in ("Sam.pdf", "passport", "Asha", "study.local", "example.com", "1234", "Tax 2025"):
            self.assertNotIn(bad, t)
        self.assertIn("[path .pdf]", t)

    def test_uo_report(self):
        inst = Install("report")
        try:
            inst.write("Private/asha-passport.txt", "secret words")
            inst.uo("scan")
            out = inst.uo("report")
            path = re.search(r"Problem report: (.+\.txt)", out)[1].strip()
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("Health checks", text)
            self.assertNotIn("asha-passport", text)
            self.assertNotIn(inst.files, text)
        finally:
            shutil.rmtree(inst.dir, ignore_errors=True)


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


class Naming(unittest.TestCase):
    def setUp(self):
        from engine import config, doctypes
        base = json.load(open(os.path.join(ROOT, "profiles", "base.json"), encoding="utf-8"))
        self.base = config.apply_region(base, "india")
        doctypes.load(self.base)

    def cfg(self, preset):
        return {**self.base, "naming_preset": preset, "entities": [{"name": "Alex Example", "type": "Self"},
                                                                    {"name": "Acme Traders", "type": "Office"}]}

    def r(self, **kw):
        return {"id": 1, "name": "scan001.pdf", "kind": "PDF", "date": "2024-03-05", "entity": "Alex Example", "doc_type": None,
                "title": None, "mtime": 1709640000, "sensitive": 0, **kw}

    def test_styles(self):
        from engine.naming import new_name, distinct
        c = self.cfg("dated")
        self.assertIsNone(new_name(self.cfg("original"), self.r()))
        self.assertEqual(new_name(c, self.r()), "2024-03-05_Alex_scan001.pdf")
        self.assertEqual(new_name(c, self.r(name="B 412 sale deed.pdf", title="Page 1 header junk")), "2024-03-05_Alex_B 412 sale deed.pdf",
                         "the text's first line is never used: the original name is")
        self.assertEqual(new_name(c, self.r(name="IMG_1.jpg", kind="Photo", doc_type="Passport")), "Alex_Passport_IMG_1.jpg")
        self.assertEqual(new_name(c, self.r(name="10th Certificate.pdf", doc_type="Certificate")), "2024-03-05_Alex_10th Certificate.pdf",
                         "a word is only taken out when the new name adds it back")
        self.assertEqual(new_name(c, self.r(name="Form - 28 - Part A.pdf")), "2024-03-05_Alex_Form - 28 - Part A.pdf", "separators kept")
        self.assertEqual(new_name(c, self.r(name="2024-07-19_AADHAAR-Dad1.pdf", doc_type="Aadhaar")), "Alex_Aadhaar_2024-07-19_Dad1.pdf",
                         "country ID types too; the type word is not repeated")
        self.assertEqual(new_name(c, self.r(name="Aadhaar.pdf", doc_type="Aadhaar")), "Alex_Aadhaar.pdf")
        txt = lambda fid: "Item 1 ... Subtotal 1,300.00\nTax 199\nGrand Total: Rs. 1,499.00"
        self.assertEqual(new_name(c, self.r(name="inv-march.pdf", doc_type="Invoice"), txt), "2024-03-05_Invoice_1499.00_inv-march.pdf")
        self.assertEqual(new_name(c, self.r(name="invoice 77.pdf", doc_type="Invoice", entity="Acme Traders"), txt),
                         "2024-03-05_Acme Traders_Invoice_1499.00_77.pdf")
        self.assertEqual(new_name(c, self.r(name="Invoice.pdf", doc_type="Invoice", date=None), lambda f: ""), None, "nothing to add")
        self.assertEqual(new_name(self.cfg("id-docs"), self.r(name="ITR ack 2023.pdf", doc_type="Form 16 / ITR")), "Alex_Form 16 - ITR_ack 2023.pdf")
        self.assertRegex(new_name(c, self.r(name="Screen Shot.png", kind="Photo", doc_type="Screenshot")),
                         r"^2024-03-05_\d\d\.\d\d_Screenshot\.png$")
        self.assertIsNone(new_name(c, self.r(name="IMG_2.jpg", kind="Photo")), "holiday photos keep their names")
        self.assertIsNone(new_name(c, self.r(sensitive=1)))
        self.assertIsNone(new_name(c, self.r(name="2024-03-05_Alex_scan001.pdf")), "already named")
        self.assertEqual(new_name(c, self.r(name='a:b*?c.pdf')), "2024-03-05_Alex_a-b-c.pdf")
        self.assertEqual(new_name(c, self.r(name="१०वीं प्रमाण पत्र.pdf")), "2024-03-05_Alex_१०वीं प्रमाण पत्र.pdf", "other scripts are kept")
        self.assertEqual(distinct("Alex_Passport.jpg", "front.jpg", {"alex_passport.jpg"}), "Alex_Passport_front.jpg")


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
            H = hub.api("/api/hub")
            ms = H["machines"]
            self.assertEqual([m["name"] for m in ms], ["Study PC"])
            self.assertEqual(ms[0]["version"], H["version"], "the agent's version is recorded at each sync")
            # updates: the state says where updates come from, never shows a token, and refuses a bad one
            U = hub.api("/api/update")
            self.assertEqual((U["kind"], U["token"]), ("github", False))
            self.assertIn("GitHub", U["source"])
            r = hub.api("/api/update/token", {"token": "not a token!"}, ok=False)
            self.assertEqual(r["_status"], 400)
            self.assertIn("GitHub token", json.dumps(r, ensure_ascii=False))
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

    def test_sorter_renames_and_undo_restores(self):
        a = Install("ren")
        try:
            p = os.path.join(a.data, "profiles", "machine.json")
            m = json.load(open(p)); m["naming_preset"] = "dated"; json.dump(m, open(p, "w"))
            tosort = os.path.join("Organized", "99_To Sort")
            a.write(os.path.join(tosort, "scan1.txt"), "Notes about the garden fence for the council")
            a.write(os.path.join(tosort, "scan2.txt"), "Other notes about the garden shed")
            a.uo("scan")
            a.admin(a.serve())
            ids = [x["id"] for x in a.api("/api/search?q=garden")["results"]]
            self.assertEqual(len(ids), 2)
            a.api("/api/label", {"ids": ids, "set": {"entity": "Alex Example", "topic": "Property"}})
            plan = a.api("/api/sort/plan", {"rename": False})
            self.assertTrue(plan["moves"] and not any(x["rename"] for x in plan["moves"]), "no renaming unless ticked")
            plan = a.api("/api/sort/plan", {"rename": True})
            mv = {x["src"].replace("\\", "/").split("/")[-1]: x for x in plan["moves"]}
            self.assertEqual(set(mv), {"scan1.txt", "scan2.txt"})
            for old, x in mv.items():
                self.assertRegex(x["rename"], r"^\d{4}-\d{2}-\d{2}_Alex_scan[12]\.txt$")
            a.api("/api/sort/run", {"ids": [x["id"] for x in plan["moves"]]})
            for _ in range(100):
                j = a.api("/api/sort/status")
                if j and j["phase"] != "running":
                    break
                time.sleep(0.2)
            self.assertEqual(j["result"]["moved"], 2, j)
            for x in mv.values():
                self.assertTrue(os.path.exists(os.path.join(x["dest_dir"], x["rename"])), x)
                self.assertFalse(os.path.exists(x["src"]))
            hit = a.api("/api/search?q=fence")["results"][0]
            self.assertEqual(os.path.basename(hit["path"]), mv["scan1.txt"]["rename"], "the catalogue follows the new name")
            run = a.api("/api/sort/runs")[0]["id"]
            self.assertEqual(a.api("/api/sort/undo", {"run": run})["undone"], 2)
            for x in mv.values():
                self.assertTrue(os.path.exists(x["src"]), "undo restores the old name and place")
            self.assertTrue(a.api("/api/search?q=fence")["results"][0]["path"].endswith("scan1.txt"))
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


class Languages(unittest.TestCase):
    """Hindi is chosen by the device's cookie, else the browser's language; English is the default; settings can set a
    computer-wide default; the dictionary never breaks the page (valid JSON, placeholders that exist in the English)."""

    def test_language_choice_and_dictionary(self):
        from engine import i18n
        self.assertIn("hi", i18n.languages())
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "i18n_extract.py"), "--check"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        i = Install("lang")
        try:
            i.serve()

            def page(headers):
                req = urllib.request.Request(i.base + "/login", headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    html = resp.read().decode("utf-8")
                return json.loads(re.search(r"window.UO_I18N=(\{.*?\});</script>", html, re.S)[1])["lang"]
            self.assertEqual(page({}), "en")
            self.assertEqual(page({"Accept-Language": "hi-IN,hi;q=0.9,en;q=0.5"}), "hi")
            self.assertEqual(page({"Cookie": "uo_lang=hi"}), "hi")
            self.assertEqual(page({"Cookie": "uo_lang=en", "Accept-Language": "hi"}), "en", "the device's own choice wins")
            self.assertEqual(page({"Cookie": "uo_lang=../../etc"}), "en", "unknown codes are ignored")
        finally:
            i.cleanup()


class WhoUsedIt(unittest.TestCase):
    def test_signins_pages_and_admin_only(self):
        i = Install("who")
        try:
            i.admin(i.serve())
            bad = i.api("/api/login", {"username": "admin", "password": "wrong password"}, ok=False)
            self.assertIn(bad["_status"], (400, 401, 403))
            i.api("/api/login", {"username": "admin", "password": "correct horse 1"})
            with i.op.open(urllib.request.Request(i.base + "/settings"), timeout=30) as r:
                r.read()
            A = i.api("/api/activity")
            me = next(a for a in A["accounts"] if a["username"] == "admin")
            self.assertGreaterEqual(me["signins_30d"], 1)
            self.assertEqual(me["failed_30d"], 1)
            self.assertGreaterEqual(me["pages_30d"], 1)
            self.assertEqual(me["last_device"], "this computer")
            self.assertEqual([e["event"] for e in A["events"]][-2:], ["signin", "signin-failed"])
            i.api("/api/users/add", {"username": "sam", "display": "Sam", "role": "member", "scope": [], "password": "member pass 1"})
            i.api("/api/logout", {})
            i.api("/api/login", {"username": "sam", "password": "member pass 1"})
            self.assertEqual(i.api("/api/activity", ok=False)["_status"], 403, "only admins see who used it")
        finally:
            i.cleanup()


def _test_key():
    """A small RSA key for the tests only (the real one never leaves the publisher), made with nothing but Python."""
    import random
    rnd = random.Random(7)

    def prime(bits):
        while True:
            c = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
            if all(pow(rnd.randrange(2, c - 1), c - 1, c) == 1 for _ in range(24)) and all(c % q for q in (3, 5, 7, 11, 13)):
                return c
    e = 65537
    while True:
        p_, q_ = prime(512), prime(512)
        phi = (p_ - 1) * (q_ - 1)
        if p_ != q_ and phi % e:
            return p_ * q_, e, pow(e, -1, phi)


def _sign(data, key):
    import hashlib
    from engine import signing
    n, e, d = key
    k = (n.bit_length() + 7) // 8
    em = b"\x00\x01" + b"\xff" * (k - 3 - len(signing._DIGEST_INFO) - 32) + b"\x00" + signing._DIGEST_INFO + hashlib.sha256(data).digest()
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


class Updates(unittest.TestCase):
    """A fake release served from local files: the newer program is checksum-checked and installed over a copy by the
    release's own installer, the profile is kept; a download that does not match its checksum changes nothing."""

    def setUp(self):
        import hashlib, io, zipfile
        from engine import updates
        self.U = updates
        self.tmp = tempfile.mkdtemp(prefix="uo-upd-")
        self.inst = os.path.join(self.tmp, "Universal Organiser")
        shutil.copytree(ROOT, self.inst, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__", "logs", "catalogue", "machine.json"))
        os.makedirs(os.path.join(self.inst, "profiles"), exist_ok=True)
        with open(os.path.join(self.inst, "profiles", "machine.json"), "w") as f:
            f.write('{"profile": "keep-me"}')
        new = os.path.join(self.tmp, "new", "universal-organiser")
        shutil.copytree(ROOT, new, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__", "logs", "catalogue", "machine.json"))
        sp = os.path.join(new, "engine", "setup.py")
        with open(sp, encoding="utf-8") as f:
            src = f.read()
        with open(sp, "w", encoding="utf-8") as f:
            f.write(re.sub(r'VERSION = "[^"]+"', 'VERSION = "99.0.0"', src))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for dp, dn, fn in os.walk(new):
                for n in fn:
                    full = os.path.join(dp, n)
                    z.write(full, os.path.relpath(full, os.path.dirname(new)))
        self.zip = buf.getvalue()
        self.sums = f"{hashlib.sha256(self.zip).hexdigest()}  universal-organiser-99.0.0.zip\n".encode()
        from engine import signing
        self.key = _test_key()
        self.orig_keys = signing.PUBLIC_KEYS
        signing.PUBLIC_KEYS = {"test": (self.key[0], self.key[1])}
        self.sig = _sign(self.sums, self.key)
        rel = {"tag_name": "v99.0.0", "html_url": "https://example.invalid/r", "body": "notes",
               "assets": [{"name": "universal-organiser-99.0.0.zip", "browser_download_url": "zip"},
                          {"name": "SHA256SUMS", "browser_download_url": "sums"},
                          {"name": "SHA256SUMS.sig", "browser_download_url": "sig"}]}
        self.files = {"zip": self.zip, "sums": self.sums, "sig": self.sig}
        self.rel = rel
        self.calls = []
        self.orig = (updates._get, updates.ROOT, updates.CACHE, updates.TOKEN_FILE, os.environ.pop("UO_UPDATE_TOKEN", None))

        def fake_get(url, timeout=15, tok=None, accept=None):
            self.calls.append((url, tok, accept))
            if url.startswith("https://api.github.com/repos/") and url.endswith("/releases/latest"):
                return io.BytesIO(json.dumps(self.rel).encode())
            if url.startswith("https://api.github.com/repos/") and "/assets/" in url:
                return io.BytesIO(self.files[url.rsplit("/", 1)[1]])
            if url.startswith("https://api.github.com/repos/"):
                return io.BytesIO(b"{}")
            return io.BytesIO(self.files[url])
        updates._get = fake_get
        updates.ROOT, updates.CACHE = self.inst, os.path.join(self.tmp, "update-check.json")
        updates.TOKEN_FILE = os.path.join(self.tmp, "update-token")

    def tearDown(self):
        self.U._get, self.U.ROOT, self.U.CACHE, self.U.TOKEN_FILE, env = self.orig
        from engine import signing
        signing.PUBLIC_KEYS = self.orig_keys
        if env is not None:
            os.environ["UO_UPDATE_TOKEN"] = env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def version_of(self):
        with open(os.path.join(self.inst, "engine", "setup.py"), encoding="utf-8") as f:
            return re.search(r'VERSION = "([^"]+)"', f.read())[1]

    def test_check_and_install(self):
        info = self.U.check({}, force=True)
        self.assertTrue(info["newer"]); self.assertEqual(info["latest"], "99.0.0")
        self.assertEqual(self.U.cached({})[0]["latest"], "99.0.0")
        self.assertIsNone(self.U.check({"updates": {"check": False}}), "turned off: no check")
        log = []
        self.assertEqual(self.U.install({}, log=log.append), "99.0.0", "\n".join(map(str, log)))
        self.assertEqual(self.version_of(), "99.0.0")
        with open(os.path.join(self.inst, "profiles", "machine.json")) as f:
            self.assertEqual(f.read(), '{"profile": "keep-me"}')

    def test_bad_checksum_changes_nothing(self):
        self.files["zip"] = self.zip + b"tampered"
        before = self.version_of()
        with self.assertRaises(SystemExit) as e:
            self.U.install({}, log=lambda m: None)
        self.assertIn("checksum", str(e.exception))
        self.assertEqual(self.version_of(), before)

    def test_unsigned_or_forged_release_is_refused(self):
        """Only the publisher's signature lets an update in: missing or forged, nothing changes."""
        before = self.version_of()
        self.files["sig"] = _sign(self.sums + b"x", self.key)  # a signature of something else
        with self.assertRaises(SystemExit) as e:
            self.U.install({}, log=lambda m: None)
        self.assertIn("not valid", str(e.exception))
        self.rel["assets"] = self.rel["assets"][:2]  # no signature at all
        with self.assertRaises(SystemExit) as e:
            self.U.install({}, log=lambda m: None)
        self.assertIn("not signed", str(e.exception))
        self.assertEqual(self.version_of(), before)
        self.assertEqual(self.U.install({"updates": {"allow_unsigned": True}}, log=lambda m: None), "99.0.0",
                         "allowed explicitly in the profile (an own unsigned update folder)")

    def test_signed_feed(self):
        """uo package --feed --sign with an OpenSSL key: the folder verifies with that key built in, and an update from it installs."""
        import subprocess
        from engine import signing
        if not shutil.which("openssl"):
            self.skipTest("openssl not installed")
        pem = os.path.join(self.tmp, "k.pem")
        subprocess.run(["openssl", "genrsa", "-out", pem, "2048"], check=True, capture_output=True)
        mod = subprocess.run(["openssl", "rsa", "-in", pem, "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout
        signing.PUBLIC_KEYS = {"openssl-test": (int(mod.strip().split("=")[1], 16), 65537)}
        feed = os.path.join(self.tmp, "signed")
        self.U.write_feed(feed, "n", pem)
        with open(os.path.join(feed, "SHA256SUMS"), "rb") as f, open(os.path.join(feed, "SHA256SUMS.sig"), "rb") as g:
            self.assertTrue(signing.verify(f.read(), g.read()))
        self.U.write_feed(feed, "n")  # re-written unsigned: the old signature is removed, not left to mismatch
        self.assertFalse(os.path.exists(os.path.join(feed, "SHA256SUMS.sig")))

    def test_private_repository_with_token(self):
        """A saved token is sent to the GitHub API only, assets come through the API, and it is kept readable only by you."""
        self.rel["assets"] = [{"name": "universal-organiser-99.0.0.zip", "browser_download_url": "nope",
                               "url": "https://api.github.com/repos/o/r/releases/assets/zip"},
                              {"name": "SHA256SUMS", "browser_download_url": "nope",
                               "url": "https://api.github.com/repos/o/r/releases/assets/sums"},
                              {"name": "SHA256SUMS.sig", "browser_download_url": "nope",
                               "url": "https://api.github.com/repos/o/r/releases/assets/sig"}]
        with self.assertRaises(ValueError):
            self.U.set_token({}, "not a token!")
        self.assertIn("saved", self.U.set_token({}, "github_pat_" + "a" * 40))
        if os.name != "nt":
            self.assertEqual(os.stat(self.U.TOKEN_FILE).st_mode & 0o777, 0o600)
        self.assertEqual(self.U.install({}, log=lambda m: None), "99.0.0")
        tok = "github_pat_" + "a" * 40
        self.assertTrue(all(t == tok for u, t, a in self.calls if u.startswith("https://api.github.com/")))
        self.assertIn(("https://api.github.com/repos/o/r/releases/assets/zip", tok, "application/octet-stream"), self.calls)
        self.assertNotIn("nope", [u for u, t, a in self.calls])
        self.assertIn("removed", self.U.set_token({}, ""))
        self.assertFalse(os.path.exists(self.U.TOKEN_FILE))

    def test_token_never_follows_a_redirect_elsewhere(self):
        import urllib.request
        h = self.U._KeepTokenHome()
        req = urllib.request.Request("https://api.github.com/repos/o/r/releases/assets/1", headers={"Authorization": "Bearer x"})
        same = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/other")
        away = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/file")
        self.assertEqual(same.get_header("Authorization"), "Bearer x")
        self.assertIsNone(away.get_header("Authorization"))

    def test_update_from_a_folder(self):
        """updates.feed = a folder with latest.json, the zip and SHA256SUMS: no GitHub involved."""
        feed = os.path.join(self.tmp, "feed")
        os.makedirs(feed)
        with open(os.path.join(feed, "universal-organiser-99.0.0.zip"), "wb") as f:
            f.write(self.zip)
        with open(os.path.join(feed, "SHA256SUMS"), "wb") as f:
            f.write(self.sums)
        with open(os.path.join(feed, "SHA256SUMS.sig"), "wb") as f:
            f.write(self.sig)
        with open(os.path.join(feed, "latest.json"), "w") as f:
            json.dump({"version": "99.0.0", "zip": "universal-organiser-99.0.0.zip", "notes": "from the folder"}, f)
        cfg = {"updates": {"feed": feed}}
        info = self.U.check(cfg, force=True)
        self.assertTrue(info["newer"], info)
        self.assertEqual(info["source"], feed)
        self.assertEqual(self.U.install(cfg, log=lambda m: None), "99.0.0")
        self.assertEqual(self.version_of(), "99.0.0")
        self.assertEqual(self.calls, [], "nothing asked of GitHub")
        self.assertIsNotNone(self.U.check_feed("http://example.com/x"))
        self.assertIsNotNone(self.U.check_feed(os.path.join(self.tmp, "missing")))
        self.assertIsNone(self.U.check_feed(feed))

    def test_write_feed(self):
        feed = os.path.join(self.tmp, "out")
        zpath, digest = self.U.write_feed(feed, "notes")
        with open(os.path.join(feed, "latest.json")) as f:
            meta = json.load(f)
        self.assertEqual(meta["zip"], os.path.basename(zpath))
        self.assertEqual(self.U.read_sums(os.path.join(feed, "SHA256SUMS"))[meta["zip"]], digest)
        import zipfile
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
        self.assertIn("universal-organiser/install/install.sh", names)
        self.assertFalse([n for n in names if "machine.json" in n or n.endswith(".pyc") or "/logs/" in n])

    def test_paired_computer_updates_from_the_hub(self):
        """The hub serves its own program at /api/agent/update; the agent checks it and installs it."""
        import hashlib, threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from engine import agent
        body, digest = self.zip, hashlib.sha256(self.zip).hexdigest()

        class Hub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                ok = self.path == "/api/agent/update" and self.headers.get("Authorization") == "Bearer T"
                self.send_response(200 if ok else 401)
                self.send_header("X-SHA256", digest); self.send_header("X-Version", "99.0.0")
                self.send_header("Content-Length", str(len(body) if ok else 0)); self.end_headers()
                if ok:
                    self.wfile.write(body)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Hub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}"
            self.assertEqual(agent.update_from_hub(url, "T", None, log=lambda m: None), "99.0.0")
            self.assertEqual(self.version_of(), "99.0.0")
            digest = "0" * 64  # a wrong checksum: nothing installed
            self.assertIsNone(agent.update_from_hub(url, "T", None, log=lambda m: None))
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
