"""Re-apply the profile's rules (document type, owner, topic) to the catalogue using the text it already holds.
Never opens a user file. Works in two steps: compute() previews what would change, apply() writes it (undoable).
A person's own decisions always win over rules."""
import json, time
from .plugins import classify
from .catalogue import LABEL_COLS

STEPS = (("doc_type", classify.DocType), ("entities", classify.Entities), ("topics", classify.Topics))


def _norm(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def compute(cfg, cat, progress=lambda done, total: None):
    total = cat.db.execute("SELECT count(*) FROM files").fetchone()[0]
    steps = [s for name, s in STEPS if cfg.plugin(name).get("enabled")]
    spoken = cfg.plugin("transcribe").get("label_from_transcript", False)
    updates, counts, sample, done = [], {"entity": 0, "doc_type": 0, "topic": 0}, [], 0
    cur = cat.db.execute(f"SELECT f.id,f.path,f.name,f.kind,f.unit,f.ext,f.hash,{','.join('f.' + c for c in LABEL_COLS)}, "
                         "coalesce(x.body,'') AS body FROM files f LEFT JOIN fts x ON x.rowid=f.id")
    while True:
        rows = cur.fetchmany(400)
        if not rows:
            break
        recs = []
        for r in rows:
            recs.append({"id": r["id"], "path": r["path"], "name": r["name"], "kind": r["kind"], "unit": r["unit"],
                         "ext": r["ext"], "hash": r["hash"], "_old": {c: r[c] for c in LABEL_COLS},
                         # transcripts are for search; they decide labels only if the profile says so
                         "text": r["body"] if spoken else r["body"].split("\n[transcript]\n")[0]})
        for s in steps:
            s.run(recs, cfg)
        for rec in recs:
            d = cat.decision_for(rec["path"], rec["hash"])
            if d:
                rec.update(d)
            new = {c: _norm(rec.get(c)) for c in LABEL_COLS}
            old = rec["_old"]
            if new != old:
                updates.append((rec["id"], new))
                for c in counts:
                    if new[c] != old[c]:
                        counts[c] += 1
                if len(sample) < 200:
                    sample.append({"path": rec["path"],
                                   "changes": [[c, old[c], new[c]] for c in ("entity", "doc_type", "topic") if new[c] != old[c]]})
        done += len(rows)
        progress(done, total)
    return {"updates": updates, "counts": counts, "files": len(updates), "sample": [s for s in sample if s["changes"]][:200],
            "computed_at": time.time()}


def apply(cat, result, by):
    c = result["counts"]
    summary = (f"Re-applied rules: {result['files']:,} files changed "
               f"(owner {c['entity']:,}, document type {c['doc_type']:,}, topic {c['topic']:,})")
    return cat.relabel(result["updates"], by, summary)
