"""The index's date and its signature (catalog-sign.py), and the word the
check gives an official entry (catalog-check.py).

A signature says who made an index, never that it is the newest: an install
orders two signed indexes by `generated` and refuses the older, so signing
stamps it, forward only, and changes nothing else of the file.

    python3 -m unittest discover -s tools -p 'test_*.py'
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, env_root=None):
    """One of the tools as a module, reading the catalog at env_root."""
    was = os.environ.get("CATALOG_ROOT")
    if env_root:
        os.environ["CATALOG_ROOT"] = env_root
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, name + ".py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if was is None:
            os.environ.pop("CATALOG_ROOT", None)
        else:
            os.environ["CATALOG_ROOT"] = was


try:
    import cryptography  # noqa: F401
    CRYPTO = True
except ImportError:
    CRYPTO = False

# Laid out as no json.dump would: the stamp must leave all of it alone.
TEXT = ('{\n "version": 1,\n   "generated": "2026-11-12T21:34:58Z",\n "formats": {},\n'
        ' "packs": [\n  {"name": "abc", "about": "says \\"generated\\": \\"never\\" in its words"}\n ]\n}\n')


class Stamp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.index = os.path.join(self.d, "index.json")
        with open(self.index, "w", encoding="utf-8") as f:
            f.write(TEXT)
        self.cs = load("catalog-sign", self.d)

    def text(self):
        with open(self.index, encoding="utf-8") as f:
            return f.read()

    def test_only_the_date_moves(self):
        said = self.cs.stamp(now=1795000000)
        self.assertEqual(said, "2026-11-18T11:06:40Z")
        self.assertEqual(self.text(), TEXT.replace("2026-11-12T21:34:58Z", said))

    def test_never_back(self):
        # A clock behind the index's own date: one second after that date.
        self.assertEqual(self.cs.stamp(now=1000), "2026-11-12T21:34:59Z")
        self.assertEqual(self.cs.stamp(now=1000), "2026-11-12T21:35:00Z")

    def test_an_index_with_no_date_gets_one(self):
        with open(self.index, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "formats": {}, "packs": []}, f)
        said = self.cs.stamp(now=1795000000)
        self.assertEqual(json.loads(self.text()), {"version": 1, "formats": {}, "packs": [], "generated": said})

    def test_a_date_that_is_no_date_is_replaced(self):
        with open(self.index, "w", encoding="utf-8") as f:
            f.write(TEXT.replace("2026-11-12T21:34:58Z", "soon"))
        self.assertEqual(self.cs.stamp(now=1795000000), "2026-11-18T11:06:40Z")
        self.assertEqual(json.loads(self.text())["generated"], "2026-11-18T11:06:40Z")

    @unittest.skipUnless(CRYPTO, "the cryptography library is not here")
    def test_signing_stamps_and_the_signature_is_of_the_stamped_index(self):
        import contextlib
        import io
        key, pub = os.path.join(self.d, "key"), os.path.join(self.d, "pub")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cs.keygen(key)
        with open(pub, "w", encoding="utf-8") as f:
            f.write(out.getvalue())
        was = json.loads(self.text())
        was["packs"][0]["maker"] = "Somebody"
        was["packs"][0].update(url="https://github.com/o/r", commit="a" * 40, sha256="0" * 64, tier="vetted",
                               withdrawn=False, platforms=["linux"])
        with open(self.index, "w", encoding="utf-8") as f:
            json.dump(was, f, indent=1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.cs.sign(key)
            first = json.loads(self.text())["generated"]
            self.cs.verify(pub)
            self.cs.sign(key)
            second = json.loads(self.text())["generated"]
            self.cs.verify(pub)
            # --as-is signs the date it carries.
            self.cs.sign(key, as_is=True)
            self.cs.verify(pub)
        self.assertNotEqual(first, "2026-11-12T21:34:58Z")
        self.assertGreater(second, first)
        self.assertEqual(json.loads(self.text())["generated"], second)
        # A stamp after the signature is no longer what was signed.
        self.cs.stamp()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            self.cs.verify(pub)


class OfficialWord(unittest.TestCase):
    """An AerieOS that takes `official` from its caller is told the entry's
    own tier; one from before it is called as it always was."""
    SELF = "https://github.com/aquilaelabs/aerieos-catalog"

    def entry(self, tier, path):
        return {"name": "jdk", "url": self.SELF, "commit": "a" * 40, "sha256": "0" * 64, "tier": tier, "withdrawn": False,
                "about": "jdk", "platforms": ["linux"], "maker": "Somebody", "path": path}

    def manifest(self, tier):
        return {"manifest": {"name": "jdk", "platforms": ["linux"], **({"tier": "official"} if tier == "official" else {})}}

    def test_a_new_aerieos_is_told(self):
        cc, seen = load("catalog-check"), []

        class New:
            @staticmethod
            def fetch(url, commit="", shipped=(), sha256="", path="", official=False):
                seen.append(official)
                return self.manifest("official" if official else "url")
        self.assertEqual(cc.check_entry(self.entry("official", "packs/official/jdk"), New, None), [])
        self.assertEqual(cc.check_entry(self.entry("aerie", "packs/aerie/jdk"), New, None), [])
        self.assertEqual(seen, [True, False])

    def test_an_older_aerieos_is_called_as_before(self):
        cc, seen = load("catalog-check"), []

        class Old:
            @staticmethod
            def fetch(url, commit="", shipped=(), sha256="", path=""):
                seen.append((commit, sha256, path))
                return self.manifest("official")
        self.assertEqual(cc.check_entry(self.entry("official", "packs/official/jdk"), Old, None), [])
        self.assertEqual(seen, [("a" * 40, "0" * 64, "packs/official/jdk")])


if __name__ == "__main__":
    unittest.main()
