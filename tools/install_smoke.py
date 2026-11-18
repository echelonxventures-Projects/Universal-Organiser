"""Check a fresh install made by install/install.sh or install/install.cmd (used by CI on macOS, Windows and Linux).

  python tools/install_smoke.py INSTALL_DIR first          after the first install: files, launcher, doctor, scan, search, page
  python tools/install_smoke.py INSTALL_DIR after-update   after running the installer again: your profile and catalogue kept

It runs the *installed* launcher (uo / uo.cmd), not the repository's code. The profile it writes uses an unencrypted test
catalogue (CI machines have no disk encryption) and a throwaway folder of sample files.
"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request

WIN = os.name == "nt"


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def uo(d, *args, check=True):
    cmd = (["cmd", "/c", os.path.join(d, "uo.cmd")] if WIN else [os.path.join(d, "uo")]) + list(args)
    env = {k: v for k, v in os.environ.items() if k != "UO_DATA"}  # the install's own data folder, as a user would have it
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900)
    out = r.stdout + r.stderr
    print(f"$ uo {' '.join(args)}  (exit {r.returncode})\n" + "\n".join("    " + l for l in out.splitlines()[-25:]))
    if check and r.returncode:
        fail(f"uo {' '.join(args)} exited with {r.returncode}")
    return out


def files_present(d):
    need = ["engine/cli.py", "engine/server.py", "engine/welcome.html", "profiles/base.json", "profiles/presets",
            "profiles/regions/india.json", "docs/manual.md", "LICENSE", "README.md", "install/install.sh",
            "uo.cmd" if WIN else "uo"]
    missing = [p for p in need if not os.path.exists(os.path.join(d, p))]
    if missing:
        fail("missing after install: " + ", ".join(missing))
    for bad in ("tests", ".git", ".github", "engine.old"):
        if os.path.exists(os.path.join(d, bad)):
            fail(f"{bad} should not be installed")
    if not WIN and not os.access(os.path.join(d, "uo"), os.X_OK):
        fail("uo is not executable")
    if sys.platform == "darwin" and os.environ.get("UO_EXPECT_HELPER") and not os.path.exists(os.path.join(d, "helpers/macos/fehelper")):
        fail("the macOS reader (fehelper) was not built")
    print("ok: program files in place")


def write_profile(d):
    sample = tempfile.mkdtemp(prefix="uo-smoke-files-")
    os.makedirs(os.path.join(sample, "Bills"))
    with open(os.path.join(sample, "Bills", "electricity-march.txt"), "w", encoding="utf-8") as f:
        f.write("Electricity bill\nAccount 12345\nTotal amount due 1,499.00\nzebrafinch\n")
    sys.path.insert(0, d)
    os.environ["UO_DATA"] = d
    from engine import setup as SU  # the installed copy
    m = SU.build_profile({"preset": "personal", "region": "none", "roots": [sample], "role": "standalone",
                          "library": os.path.join(sample, "Organized"), "you": "Alex Example", "access": "local"})
    del os.environ["UO_DATA"]
    m["catalogue"] = {"encrypted": False, "allow_unencrypted_disk": True}
    m["ui"] = {"port": free_port(), "lan": {"enabled": False, "port": free_port()}}
    m["plugins"] = {"transcribe": {"enabled": False}, "near_duplicate_photos": {"enabled": False}}
    os.makedirs(os.path.join(d, "profiles"), exist_ok=True)
    with open(os.path.join(d, "profiles", "machine.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
    return m


def page_opens(d, port):
    cmd = (["cmd", "/c", os.path.join(d, "uo.cmd")] if WIN else [os.path.join(d, "uo")]) + ["serve", "--no-browser"]
    env = {k: v for k, v in os.environ.items() if k != "UO_DATA"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        t0, last = time.time(), None
        while time.time() - t0 < 90:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=5) as r:
                    html = r.read().decode("utf-8", "replace")
                if r.status == 200 and "<html" in html.lower():
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/login-state",
                                                                       headers={"X-FE": "1"}), timeout=5) as r2:
                        state = json.loads(r2.read())
                    print(f"ok: the page opens on port {port} (login state: {state})")
                    return
            except Exception as e:  # not up yet
                last = e
            time.sleep(1)
        fail(f"the page did not open on port {port}: {last}")
    finally:
        if WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.terminate()
        try:
            out = p.communicate(timeout=15)[0].decode("utf-8", "replace")
            print("    server said:\n" + "\n".join("    " + l for l in out.splitlines()[-10:]))
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ("first", "after-update"):
        print(__doc__); sys.exit(2)
    d, stage = os.path.abspath(sys.argv[1]), sys.argv[2]
    files_present(d)
    if stage == "first":
        if os.path.exists(os.path.join(d, "profiles", "machine.json")):
            fail("a fresh install already has a machine profile (personal data must never ship)")
        if "uo" not in uo(d, "help").lower():
            fail("uo help printed nothing useful")
        uo(d, "doctor", check=False)  # before any profile: must not crash
        m = write_profile(d)
        out = uo(d, "doctor", check=False)
        if "Traceback" in out:
            fail("uo doctor crashed")
        uo(d, "scan")
        if "electricity-march" not in uo(d, "search", "zebrafinch"):
            fail("search did not find the sample file after the scan")
        page_opens(d, m["ui"]["port"])
        print("PASS: fresh install works")
    else:
        mp = os.path.join(d, "profiles", "machine.json")
        if not os.path.exists(mp):
            fail("updating removed your machine profile")
        port = json.load(open(mp, encoding="utf-8"))["ui"]["port"]
        if "electricity-march" not in uo(d, "search", "zebrafinch"):
            fail("updating lost the catalogue")
        page_opens(d, port)
        print("PASS: update kept your profile and catalogue")


if __name__ == "__main__":
    main()
