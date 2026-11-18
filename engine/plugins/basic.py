import os, hashlib


class Metadata:
    NAME, PLATFORMS, CONTENT = "metadata", {"any"}, False

    @staticmethod
    def run(batch, cfg):
        for r in batch:
            if r.get("unit") != "file":
                continue
            r["kind"] = cfg.kind_of.get(r["ext"], "Other")


class Hash:
    NAME, PLATFORMS, CONTENT = "hash", {"any"}, True

    @staticmethod
    def run(batch, cfg):
        cap = cfg.plugin("hash").get("full_hash_max_mb", 300) * 1e6
        for r in batch:
            if r.get("unit") != "file" or r.get("skip_content") or not r["size"]:
                continue
            h = hashlib.blake2b(digest_size=16)
            try:
                with open(r["path"], "rb") as f:
                    if r["size"] <= cap:
                        for b in iter(lambda: f.read(1 << 20), b""):
                            h.update(b)
                        r["hash"] = h.hexdigest()
                    else:  # large file: size + first/last 8 MB
                        h.update(str(r["size"]).encode()); h.update(f.read(8 << 20)); f.seek(-8 << 20, 2); h.update(f.read())
                        r["hash"] = "p:" + h.hexdigest()
            except OSError as e:
                r.setdefault("errs", []).append(f"hash: {e.strerror}")
