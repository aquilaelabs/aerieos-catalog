"""The index's date, its signature and its shape (catalog-sign.py).

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
                               withdrawn=False, platforms=["linux"], held="pinned")
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


def entry(**more):
    return {"name": "abc", "url": "https://github.com/o/r", "commit": "a" * 40, "sha256": "0" * 64, "tier": "vetted", "withdrawn": False,
            "about": "abc", "platforms": ["linux"], "maker": "Somebody", "held": "pinned", **more}


class Shape(unittest.TestCase):
    """What the index must be before it is signed: what an entry's downloads
    are held to, its older pins, and which AerieOS first reads each format."""

    def setUp(self):
        self.cs = load("catalog-sign")

    def bad(self, *packs, formats=None, **kw):
        return self.cs.check_index({"version": 1, "formats": formats or {}, "packs": list(packs)}, **kw)

    def test_an_entry_as_the_tools_write_it(self):
        self.assertEqual(self.bad(entry()), [])
        self.assertEqual(self.bad(entry(held="installer", online="Its installer downloads the rest from its vendor.")), [])
        self.assertEqual(self.bad(entry(kind="app", format=5, framework="5.2"), formats={"5": "0.9.0"}), [])

    def test_nothing_offered_is_open_or_says_no_word(self):
        self.assertTrue(any("held is open" in b for b in self.bad(entry(held="open"))))
        gone = entry()
        del gone["held"]
        self.assertTrue(any("held is what its downloads are held to" in b for b in self.bad(gone)))
        self.assertTrue(any("held is what its downloads are held to" in b for b in self.bad(entry(held="mostly"))))
        # One that is withdrawn is offered to nobody: the words alone.
        self.assertEqual(self.bad({**gone, "withdrawn": True}), [])
        self.assertEqual(self.bad(entry(held="open", withdrawn=True)), [])
        self.assertTrue(self.bad(entry(held="mostly", withdrawn=True)))

    def test_online_is_an_installers_sentence(self):
        self.assertTrue(any("online is an installer's own sentence" in b for b in self.bad(entry(online="It downloads the rest by itself."))))
        self.assertTrue(any("online is an installer's own sentence" in b for b in self.bad(entry(held="installer", online="x"))))

    def test_older_pins(self):
        pin = {"format": 5, "framework": "5.2", "commit": "b" * 40, "sha256": "1" * 64, "held": "pinned"}
        ok = entry(format=6, older=[pin, {"format": 3, "commit": "c" * 40, "sha256": "2" * 64, "held": "installer",
                                         "online": "Its installer downloads the rest from its vendor."}])
        self.assertEqual(self.bad(ok, formats={"3": "0.9.0", "5": "0.9.1", "6": "0.10.0"}), [])
        for wrong, said in (([{**pin, "format": 6}], "from the newest pack format down"), ([pin, pin], "from the newest pack format down"),
                            ([{**pin, "tier": "official"}], "which the entry says once"), ([{"format": 5}], "an older pin says its format"),
                            ([], "older lists up to"), ("the one before", "older lists up to"), ([{**pin, "held": "open"}], "held is open"),
                            ([{k: v for k, v in pin.items() if k != "held"}], "held is what its downloads are held to")):
            got = self.bad(entry(format=6, older=wrong), formats={"5": "0.9.1", "6": "0.10.0"})
            self.assertTrue(any(said in b for b in got), (wrong, got))

    def test_which_aerieos_first_reads_a_format(self):
        pin = {"format": 3, "commit": "b" * 40, "sha256": "1" * 64, "held": "pinned"}
        d = {"version": 1, "formats": {"2": "0.9.0"}, "packs": [entry(format=5, older=[pin])]}
        self.assertEqual(self.cs.formats_used(d), [3, 5])
        self.assertEqual(self.cs.undated(d), [3, 5])
        said = self.cs.check_index(d)
        self.assertEqual(len(said), 2, said)
        self.assertTrue(all("formats does not say which AerieOS first reads it" in b and "aerieos-release.py" in b for b in said))
        # Before any release has a version to write there, that alone is
        # left to the caller to say; everything else is still held.
        self.assertEqual(self.cs.check_index(d, dated=False), [])
        d["packs"][0]["held"] = "open"
        self.assertTrue(self.cs.check_index(d, dated=False))
        d["packs"][0]["held"], d["formats"] = "pinned", {"3": "0.9.0", "5": "0.9.0"}
        self.assertEqual(self.cs.check_index(d), [])


if __name__ == "__main__":
    unittest.main()
