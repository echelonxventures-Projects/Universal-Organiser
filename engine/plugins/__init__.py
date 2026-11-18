"""Plug-in registry. A plug-in is a module with:
  NAME      config key under "plugins"
  PLATFORMS set of platforms it runs on ({"macos","windows","linux"} or {"any"})
  CONTENT   True if it reads file contents (skipped for sensitive and iCloud-only files)
  run(batch, cfg)  mutates each record dict in the batch
Order matters: extractors first, classifiers last. New plug-ins are added here only after review (design item 26)."""
from . import basic, text, archive, macos_vision, classify

ORDER = [basic.Metadata, basic.Hash, text.Text, text.PdfText, archive.Archive, macos_vision.PDF, macos_vision.Image,
         classify.Dates, classify.DocType, classify.Entities, classify.Topics, classify.Finish]


def active(cfg):
    out = []
    for p in ORDER:
        if not cfg.plugin(p.NAME).get("enabled", False):
            continue
        if "any" not in p.PLATFORMS and cfg.platform not in p.PLATFORMS:
            continue
        out.append(p)
    return out
