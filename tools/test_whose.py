"""Whose an entry is (catalog-check.py's whose): a change that stays with
one owner passes, and each way of crossing owners is refused by name.

    python3 -m unittest discover -s tools -p 'test_*.py'
"""
import copy
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("catalog_check", os.path.join(HERE, "catalog-check.py"))
assert spec and spec.loader
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

SELF = "https://github.com/aquilaelabs/aerieos-catalog"


def entry(name, tier, url=SELF, commit="a" * 40, **more):
    return {"name": name, "url": url, "commit": commit, "sha256": "0" * 64, "tier": tier, "withdrawn": False,
            "about": name, "platforms": ["linux"], "maker": "Somebody", **more}


def index(*packs):
    return {"version": 1, "formats": {}, "packs": list(packs)}


JDK = entry("jdk", "official", path="packs/official/jdk")
GEM = entry("gemini", "aerie", path="packs/aerie/gemini")
ACME = entry("acme-cli", "vetted", url="https://github.com/acme/aerie-pack")
OTHER = entry("other-tool", "vetted", url="https://github.com/other/pack")
KEPT = entry("kept-here", "vetted", path="packs/kept-here")
BASE = index(JDK, GEM, ACME, OTHER, KEPT)


def after(**changes):
    """BASE with each named entry's fields changed (None removes it)."""
    d = copy.deepcopy(BASE)
    for name, fields in changes.items():
        name = name.replace("_", "-")
        if fields is None:
            d["packs"] = [p for p in d["packs"] if p["name"] != name]
        else:
            next(p for p in d["packs"] if p["name"] == name).update(fields)
    return d


class Whose(unittest.TestCase):
    def bad(self, now, files=("index.json",)):
        return cc.whose(BASE, now, files)[1]

    def test_owner(self):
        self.assertEqual(cc.owner_of(JDK), "")
        self.assertEqual(cc.owner_of(GEM), "")
        self.assertEqual(cc.owner_of(ACME), "https://github.com/acme/")
        self.assertEqual(cc.owner_of(KEPT), "this repository's packs/kept-here")

    def test_nothing_changed(self):
        self.assertEqual(cc.whose(BASE, copy.deepcopy(BASE), ()), ([], []))

    def test_aeries_own_alone(self):
        now = after(jdk={"commit": "b" * 40, "sha256": "1" * 64}, gemini={"about": "new words"})
        lines, bad = cc.whose(BASE, now, ("index.json", "packs/official/jdk/bbtool.json", "tools/catalog-check.py", "README.md"))
        self.assertEqual(bad, [])
        self.assertTrue(any("jdk: Aerie's, pin moved" in ln for ln in lines), lines)

    def test_a_third_partys_pin_alone(self):
        now = after(acme_cli={"commit": "b" * 40, "sha256": "1" * 64, "framework": "2.2", "maker": "Acme"})
        lines, bad = cc.whose(BASE, now, ("index.json", "index.sig"))
        self.assertEqual(bad, [])
        self.assertTrue(any("acme-cli: https://github.com/acme/'s, pin moved" in ln for ln in lines), lines)

    def test_a_new_submission(self):
        now = copy.deepcopy(BASE)
        now["packs"].append(entry("new-tool", "vetted", url="https://gitlab.com/newco/pack"))
        self.assertEqual(self.bad(now), [])

    def test_the_maintainers_two(self):
        self.assertEqual(self.bad(after(acme_cli={"withdrawn": True})), [])
        self.assertEqual(self.bad(after(acme_cli={"tier": "verified"})), [])

    def test_aeries_and_a_third_partys_together(self):
        now = after(jdk={"commit": "b" * 40}, acme_cli={"commit": "b" * 40})
        self.assertTrue(any("one or the other, never both" in b for b in self.bad(now)))

    def test_two_owners_together(self):
        now = after(acme_cli={"commit": "b" * 40}, other_tool={"commit": "c" * 40})
        self.assertTrue(any("more than one owner" in b for b in self.bad(now)))

    def test_no_new_pin(self):
        for field, value in (("maker", "Somebody Else"), ("about", "other words"), ("sha256", "2" * 64), ("path", "elsewhere")):
            said = self.bad(after(acme_cli={field: value}))
            self.assertTrue(any(f"{field} changed with no new pin" in b for b in said), (field, said))

    def test_its_address_never(self):
        now = after(acme_cli={"url": "https://github.com/acme/another", "commit": "b" * 40})
        self.assertTrue(any("never changes its url" in b for b in self.bad(now)))

    def test_changes_hands(self):
        said = self.bad(after(acme_cli={"url": "https://github.com/taker/aerie-pack", "commit": "b" * 40}))
        self.assertTrue(any("changes hands" in b for b in said), said)
        said = self.bad(after(acme_cli={"tier": "aerie", "url": SELF, "path": "packs/aerie/acme-cli", "commit": "b" * 40}))
        self.assertTrue(any("changes hands, from https://github.com/acme/ to Aerie" in b for b in said), said)

    def test_removed(self):
        self.assertTrue(any("never removed" in b for b in self.bad(after(acme_cli=None))))
        # Aerie's own may go: said, not refused.
        lines, bad = cc.whose(BASE, after(gemini=None), ("index.json",))
        self.assertEqual(bad, [])
        self.assertTrue(any("gemini: Aerie's, removed" in ln for ln in lines))

    def test_what_else_it_touches(self):
        now = after(acme_cli={"commit": "b" * 40})
        for f in ("tools/catalog-check.py", "verified-vendors.json", "catalog.pub", ".github/workflows/check.yml",
                  "packs/official/jdk/bbtool.json", "aerieos-releases"):
            self.assertTrue(any(f in b and "beside a third party's entry" in b for b in self.bad(now, ("index.json", f))), f)
        # A submission kept here moves with its own folder, and no other.
        now = after(kept_here={"commit": "b" * 40})
        self.assertEqual(self.bad(now, ("index.json", "packs/kept-here/bbtool.json")), [])
        self.assertTrue(self.bad(now, ("index.json", "packs/aerie/gemini/bbtool.json")))

    def test_from_outside(self):
        out = lambda now, files=("index.json",), added=(): cc.whose(BASE, now, files, True, added)[1]
        # Its own entry added or moved, and a pack kept here in a new folder: taken.
        now = copy.deepcopy(BASE)
        now["packs"].append(entry("new-app", "vetted", path="packs/apps/new-app", kind="app"))
        new = ("packs/apps/new-app/bbapp.json", "packs/apps/new-app/compose.yml")
        self.assertEqual(out(now, ("index.json", *new), new), [])
        self.assertEqual(out(after(acme_cli={"commit": "b" * 40})), [])
        # A pack kept here moves with its own folder's files.
        self.assertEqual(out(after(kept_here={"commit": "b" * 40}), ("index.json", "packs/kept-here/bbtool.json")), [])
        # One of Aerie's moved, or an entry added as Aerie's own: never.
        self.assertTrue(any("jdk is Aerie's own" in b for b in out(after(jdk={"about": "other words"}))))
        now = copy.deepcopy(BASE)
        now["packs"].append(entry("sneak", "aerie", path="packs/aerie/sneak"))
        self.assertTrue(any("a submission is added as vetted" in b for b in out(now)))
        # A file that was here, changed with no entry moved at all: never.
        for f in ("tools/catalog-check.py", "index.sig", "packs/official/jdk/bbtool.json", "README.md", ".github/workflows/check.yml"):
            self.assertTrue(any(f in b and "changes nothing that was here" in b for b in out(copy.deepcopy(BASE), (f,))), f)
        # ...nor a new file anywhere but packs/.
        self.assertTrue(out(copy.deepcopy(BASE), ("tools/new.py",), ("tools/new.py",)))
        # The same from inside is the maintainers' own work.
        self.assertEqual(cc.whose(BASE, after(jdk={"about": "other words"}), ("index.json", "tools/catalog-check.py"))[1], [])

    def test_the_indexs_own(self):
        now = after(acme_cli={"commit": "b" * 40})
        now["formats"] = {"3": "v1.0.0"}
        self.assertTrue(any("the index's formats" in b for b in self.bad(now)))


if __name__ == "__main__":
    unittest.main()
