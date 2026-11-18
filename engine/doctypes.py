"""Groups of document types, read from each type's "tags" in the profile (so a region pack can add its own IDs).
  id        identity documents          holder  the named holder is the owner
  dob       name printed above the date of birth
  important triage shows these first     paper   counted as an important paper without an owner
  money tax insurance medical education work property vehicle travel   sections on a person's page
"""
TYPES = []


def load(data):
    TYPES[:] = [(d["name"], set(d.get("tags", []))) for d in data.get("doc_types", [])]


def tagged(*tags):
    want = set(tags)
    return [n for n, t in TYPES if t & want]
