"""List what is inside archives without extracting anything (zipfile; bsdtar/libarchive for rar, 7z, tar)."""
import zipfile, tarfile, subprocess, shutil, re


class Archive:
    NAME, PLATFORMS, CONTENT = "archive", {"any"}, True

    @staticmethod
    def run(batch, cfg):
        cap = cfg.plugin("archive").get("max_entries", 2000)
        bsdtar = shutil.which("bsdtar") or shutil.which("tar")
        for r in batch:
            if r.get("unit") != "file" or r.get("skip_content") or r.get("kind") != "Archive":
                continue
            items = []
            try:
                if r["ext"] == "zip":
                    with zipfile.ZipFile(r["path"]) as z:
                        infos = [i for i in z.infolist() if not i.is_dir()]
                        items = [(i.filename, i.file_size) for i in infos]
                        r["inner_count"] = len(infos)
                        if any(i.flag_bits & 1 for i in infos):
                            r.setdefault("tags", []).append("password-protected")
                elif r["ext"] in ("tar", "gz", "tgz", "bz2", "xz") and tarfile.is_tarfile(r["path"]):
                    # standard library: same result on macOS, Windows and Linux
                    with tarfile.open(r["path"]) as t:
                        members = []
                        for m in t:
                            if m.isfile():
                                members.append((m.name, m.size))
                            if len(members) > cap * 5:
                                break
                    items = members
                    r["inner_count"] = len(items)
                elif bsdtar:
                    out = subprocess.run([bsdtar, "-tvf", r["path"]], capture_output=True, text=True, errors="replace", timeout=90)
                    for line in out.stdout.splitlines():
                        m = re.match(r"\S+\s+\S+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+\S+\s+(.*)$", line)
                        if m and not m[2].endswith("/"):
                            items.append((m[2], int(m[1])))
                    r["inner_count"] = len(items)
                    if out.returncode and not items:
                        r.setdefault("errs", []).append("archive: unreadable or encrypted")
            except Exception as ex:
                r.setdefault("errs", []).append(f"archive: {type(ex).__name__}")
            r["archive_items"] = items[:cap]
            if items:  # inner names become searchable text
                r["text"] = ((r.get("text") or "") + "\nContains:\n" + "\n".join(n for n, _ in items[:cap]))[:200000]
