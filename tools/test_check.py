"""The check's own rules (catalog-check.py) and the release tool
(aerieos-release.py): an entry read at the pin a release takes, no open
entry, nothing taken away from a release, and what is said while no release
is listed.

    python3 -m unittest discover -s tools -p 'test_*.py'

The readers the check uses are AerieOS's own, from a checkout. Here small
stand-ins answer for them, so the rules are held with no checkout; with
AERIEOS_CHECKOUT naming one, the rules that read an entry's pins are held
to that AerieOS's packformat too.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = "https://github.com/aquilaelabs/aerieos-catalog"
CHECKOUT = os.environ.get("AERIEOS_CHECKOUT", "")


def load(name, root=None):
    """One of the tools as a module, reading the catalog at `root`."""
    was = os.environ.get("CATALOG_ROOT")
    if root:
        os.environ["CATALOG_ROOT"] = root
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


cc = load("catalog-check")


class Format:
    """An entry's pins as AerieOS's packformat reads them: the stand-in the
    rules are held with where no checkout is named."""
    FORMAT = 5

    @staticmethod
    def of(doc):
        v = doc.get("format", 1) if isinstance(doc, dict) else 1
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None

    @staticmethod
    def topics_refused(_doc):
        return ""

    @staticmethod
    def older_refused(entry):
        older, below = entry.get("older"), entry.get("format", 1)
        if older is None:
            return ""
        if not isinstance(older, list) or not older:
            return "older lists up to 8 earlier pins of the entry"
        for pin in older:
            if not isinstance(pin, dict) or not isinstance(pin.get("format"), int) or pin["format"] >= below:
                return "earlier pins go from the newest format down"
            below = pin["format"]
        return ""

    @classmethod
    def pin_for(cls, entry, reads=None):
        reads = cls.FORMAT if reads is None else reads
        fmt = cls.of(entry)
        if fmt is None:
            return None
        own = {k: v for k, v in entry.items() if k != "older"}
        if fmt <= reads:
            return own
        pin = next((p for p in entry.get("older") or [] if p["format"] <= reads), None) if not cls.older_refused(entry) else None
        keys = ("format", "framework", "commit", "sha256", "platforms", "label", "works_with", "held", "online", "install_rev", "shipped_rev")
        return {**{k: v for k, v in own.items() if k not in keys}, **pin} if pin else None


def real_format():
    """The packformat of the AerieOS AERIEOS_CHECKOUT names, which imports
    nothing of the rest of it."""
    spec = importlib.util.spec_from_file_location("packformat_real", os.path.join(CHECKOUT, "scripts", "dashboard", "packformat.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FORMATS = [("the stand-in", Format)] + ([("the checkout's own", real_format())] if CHECKOUT else [])


def entry(name, tier="vetted", url="https://github.com/acme/pack", commit="a" * 40, **more):
    return {"name": name, "url": url, "commit": commit, "sha256": "0" * 64, "tier": tier, "withdrawn": False,
            "about": name, "platforms": ["linux/amd64"], "maker": "Somebody", "held": "pinned", **more}


def index(*packs):
    return {"version": 1, "formats": {}, "packs": list(packs)}


OLD = {"format": 5, "framework": "5.2", "commit": "b" * 40, "sha256": "1" * 64, "platforms": ["linux/amd64"], "held": "installer",
       "online": "Its installer downloads the rest from its vendor."}


class Away(unittest.TestCase):
    """Nothing is taken away from a release: what it could take of the
    index a change started from, it can still take."""

    def test_a_pack_that_moves_format_and_keeps_its_older_pin(self):
        was = index(entry("hexkit", format=5, framework="5.2"))
        now = index(entry("hexkit", format=6, commit="c" * 40, older=[OLD]))
        for what, pf in FORMATS:
            self.assertEqual(cc.away(was, now, 5, pf.pin_for), [], what)
            self.assertEqual(cc.away(was, now, 6, pf.pin_for), [], what)
            # ...and the release that reads only the older format is answered that pin.
            self.assertEqual(pf.pin_for(now["packs"][0], 5)["commit"], "b" * 40, what)

    def test_a_pack_that_moves_format_and_drops_the_pin(self):
        was = index(entry("hexkit", format=5))
        now = index(entry("hexkit", format=6, commit="c" * 40))
        for what, pf in FORMATS:
            said = cc.away(was, now, 5, pf.pin_for)
            self.assertEqual(len(said), 1, what)
            self.assertIn("hexkit has no pin left that it reads", said[0])
            self.assertIn("keeps its older pin (older) until no listed release needs it", said[0])
            # The release that reads the new format lost nothing.
            self.assertEqual(cc.away(was, now, 6, pf.pin_for), [], what)

    def test_an_older_pin_dropped_while_a_release_still_takes_it(self):
        was = index(entry("hexkit", format=6, commit="c" * 40, older=[OLD]))
        now = index(entry("hexkit", format=6, commit="c" * 40))
        for what, pf in FORMATS:
            self.assertTrue(cc.away(was, now, 5, pf.pin_for), what)
            self.assertEqual(cc.away(was, now, 6, pf.pin_for), [], what)

    def test_an_entry_removed_or_withdrawn(self):
        was = index(entry("hexkit"), entry("other"))
        for what, pf in FORMATS:
            said = cc.away(was, index(entry("other")), 5, pf.pin_for)
            self.assertTrue(len(said) == 1 and "hexkit is gone from the index" in said[0] and "withdrawn" in said[0], (what, said))
            # Withdrawn is how an entry goes: said to every install, and no failure here.
            self.assertEqual(cc.away(was, index(entry("hexkit", withdrawn=True), entry("other")), 5, pf.pin_for), [], what)
            # One that was withdrawn already, or that the release never read, owes it nothing.
            self.assertEqual(cc.away(index(entry("hexkit", withdrawn=True)), index(), 5, pf.pin_for), [], what)
            self.assertEqual(cc.away(index(entry("hexkit", format=6)), index(), 5, pf.pin_for), [], what)

    def test_a_new_entry_and_a_moved_pin(self):
        was = index(entry("hexkit"))
        now = index(entry("hexkit", commit="c" * 40), entry("new-tool"))
        for what, pf in FORMATS:
            self.assertEqual(cc.away(was, now, 5, pf.pin_for), [], what)
            self.assertEqual(cc.away({}, now, 5, pf.pin_for), [], what)


class Fetched:
    """Stand-ins for the AerieOS modules that read a folder at its pin:
    `manifests` maps a commit to what the folder says there."""

    def __init__(self, manifests, differs=()):
        self.manifests, self.said, self.asked = manifests, list(differs), []
        self.MANIFEST = "bbtool.json"

    # toolpacks
    def fetch(self, url, commit="", shipped=(), sha256="", path=""):
        self.asked.append(("fetch", url, commit, path))
        m = self.manifests.get(commit)
        if m is None:
            return {"error": f"could not fetch {url}"}
        return {"manifest": m["doc"], "held": {"word": m["held"][0], "why": m["held"][1]}}

    def fetch_folder(self, url, commit, sha256, path, files, cap=0):
        self.asked.append(("folder", url, commit, path))
        m = self.manifests.get(commit)
        if m is None:
            return {"error": f"could not fetch {url}"}
        return {"files": {name: (b"services: {}" if name == "compose.yml" else json.dumps(m["doc"]).encode()) for name in files}}

    def validate(self, doc, shipped=(), official=False):
        return dict(doc, _held=self.manifests[doc["_at"]]["held"]), []

    # nasapps
    def held_of(self, app):
        return {"word": self.held[0], "why": self.held[1]}

    # catalogentry
    def differs(self, entry, url=""):
        self.asked.append(("differs", url, entry["commit"], entry.get("path") or ""))
        return list(self.said)


def aerieos(fetched, pf=Format, held=("pinned", "every download is held")):
    fetched.held = held
    fmt = types.SimpleNamespace(of=pf.of, pin_for=pf.pin_for, older_refused=pf.older_refused, topics_refused=pf.topics_refused,
                                held=lambda m: m["_held"])
    return types.SimpleNamespace(toolpacks=fetched, nasapps=fetched, catalogentry=fetched, packformat=fmt, reads=5)


PINNED = ("pinned", "every download it makes is held to a pin")
OPEN = ("open", "its install steps run with the network, and its entry does not say what they fetch")


class Entry(unittest.TestCase):
    """One entry, at the pin a release takes of it."""

    def test_a_pack_whose_downloads_are_held(self):
        f = Fetched({"a" * 40: {"doc": {"name": "hexkit"}, "held": PINNED}})
        self.assertEqual(cc.check_entry(entry("hexkit"), aerieos(f)), [])
        # Read once for what it says of itself, and once by the reader an install uses.
        self.assertEqual(sorted(a[0] for a in f.asked), ["differs", "fetch"])

    def test_no_entry_is_open(self):
        f = Fetched({"a" * 40: {"doc": {"name": "hexkit"}, "held": OPEN}})
        said = cc.check_entry(entry("hexkit", held="open"), aerieos(f))
        self.assertEqual(len(said), 1, said)
        self.assertIn("hexkit reads open: its install steps run with the network", said[0])
        self.assertIn("The catalog holds no open entry", said[0])
        # An entry that says pinned of a manifest that reads open is refused twice
        # over: for being open, and for saying what its manifest does not.
        f = Fetched({"a" * 40: {"doc": {"name": "hexkit"}, "held": OPEN}}, differs=["the entry says held pinned and its manifest open"])
        said = cc.check_entry(entry("hexkit"), aerieos(f))
        self.assertTrue(any("reads open" in s for s in said) and any("the entry says held pinned" in s for s in said), said)

    def test_an_entry_that_says_no_word(self):
        f = Fetched({"a" * 40: {"doc": {"name": "hexkit"}, "held": PINNED}}, differs=["the entry says held (nothing) and its manifest pinned"])
        e = entry("hexkit")
        del e["held"]
        said = cc.check_entry(e, aerieos(f))
        self.assertTrue(any("says no held word" in s and "packs-export.py" in s for s in said), said)
        self.assertTrue(any("the entry says held (nothing)" in s for s in said), said)

    def test_what_its_folder_does_not_say_is_refused_in_the_readers_words(self):
        f = Fetched({"a" * 40: {"doc": {"name": "hexkit"}, "held": PINNED}},
                    differs=["the entry says format 5 and its manifest 6", "the entry says platforms ['linux/amd64'] and its manifest ['linux/arm64']"])
        said = cc.check_entry(entry("hexkit"), aerieos(f))
        self.assertEqual(said, ["hexkit: the entry says format 5 and its manifest 6",
                                "hexkit: the entry says platforms ['linux/amd64'] and its manifest ['linux/arm64']"])
        # A folder that cannot be read at the pin: said once.
        f = Fetched({}, differs=["could not fetch https://github.com/acme/pack"])
        self.assertEqual(cc.check_entry(entry("hexkit"), aerieos(f)), ["hexkit: could not fetch https://github.com/acme/pack"])

    def test_an_app(self):
        doc = {"name": "whoami", "port": 8089, "license": {"label": "MIT"}}
        e = entry("whoami", "aerie", url=SELF, path="packs/apps/whoami", kind="app")
        f = Fetched({"a" * 40: {"doc": doc, "held": PINNED}})
        self.assertEqual(cc.check_entry(e, aerieos(f, held=("pinned", "every image it runs is named by the digest its entry carries"))), [])
        # Its own repository is read from this checkout, never fetched back.
        self.assertTrue(all(a[1].startswith("file://") for a in f.asked), f.asked)
        said = cc.check_entry(e, aerieos(Fetched({"a" * 40: {"doc": doc, "held": PINNED}}),
                                         held=("open", "traefik/whoami:v1.10.4 is named by its tag alone: the registry may serve another image under it")))
        self.assertTrue(len(said) == 1 and "whoami reads open: traefik/whoami:v1.10.4 is named by its tag alone" in said[0], said)
        f = Fetched({"a" * 40: {"doc": {"name": "whoami"}, "held": PINNED}})
        said = cc.check_entry(e, aerieos(f))
        self.assertEqual(said, ["whoami: bbapp.json names no port", "whoami: bbapp.json names no license"])

    def test_an_official_entry(self):
        at = "a" * 40
        e = entry("jdk", "official", url=SELF, path="packs/official/jdk")
        f = Fetched({at: {"doc": {"name": "jdk", "tier": "official", "_at": at}, "held": PINNED}})
        self.assertEqual(cc.check_entry(e, aerieos(f)), [])
        # Its manifest is read whole, by the folder: a pack's own size does not hold it.
        self.assertIn("folder", [a[0] for a in f.asked])
        # One whose manifest is not written as AerieOS's own is no official entry.
        f = Fetched({at: {"doc": {"name": "jdk", "_at": at}, "held": PINNED}})
        self.assertEqual(cc.check_entry(e, aerieos(f)), ["jdk: the entry is official and its manifest url"])
        # ...and an official entry is one of this repository's own folders.
        said = cc.check_entry(entry("jdk", "official"), aerieos(Fetched({})))
        self.assertTrue(len(said) == 1 and "an official entry is one of this repository's own" in said[0], said)

    def test_who_it_is_by(self):
        said = cc.check_entry(entry("hexkit", maker=""), aerieos(Fetched({})))
        self.assertTrue(len(said) == 1 and "names who its tool is by" in said[0], said)


class Pins(unittest.TestCase):
    """Every pin of an entry a release reads is checked by it, the one it
    takes first."""

    def test_the_pin_a_release_takes_and_the_older_ones_it_reads(self):
        e = entry("hexkit", format=6, commit="c" * 40, older=[OLD, {"format": 3, "commit": "d" * 40, "sha256": "2" * 64, "held": "pinned"}])
        for what, pf in FORMATS:
            reads = lambda n, pf=pf: [(p["format"], p["commit"][0]) for p in cc.pins_read(e, types.SimpleNamespace(packformat=pf, reads=n))]
            self.assertEqual(reads(6), [(6, "c"), (5, "b"), (3, "d")], what)
            self.assertEqual(reads(5), [(5, "b"), (3, "d")], what)
            self.assertEqual(reads(4), [(3, "d")], what)
            self.assertEqual(reads(2), [], what)
            # A pin is whole: the older one takes nothing from the newest.
            pin = cc.pins_read(e, types.SimpleNamespace(packformat=pf, reads=5))[0]
            self.assertEqual((pin["held"], pin["online"], pin["name"], pin.get("older")), ("installer", OLD["online"], "hexkit", None), what)


class NoRelease(unittest.TestCase):
    """While aerieos-releases lists none, nothing passes for want of one."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.ar = load("aerieos-release", self.d)
        with open(os.path.join(self.d, "aerieos-releases"), "w", encoding="utf-8") as f:
            f.write(self.ar.releases_text([]))
        self.index = index(entry("hexkit", "aerie", url=SELF, path="packs/aerie/hexkit", format=5, framework="5.2"))
        self.write(self.index)
        self.cc = load("catalog-check", self.d)

    def write(self, d):
        with open(os.path.join(self.d, "index.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(d, indent=1) + "\n")

    def run_check(self, *argv):
        # The signing tool the check loads reads the same catalog.
        out, was = io.StringIO(), os.environ.get("CATALOG_ROOT")
        os.environ["CATALOG_ROOT"] = self.d
        try:
            with contextlib.redirect_stdout(out):
                try:
                    code = self.cc.main(list(argv))
                except SystemExit as e:
                    code = e.code
        finally:
            if was is None:
                os.environ.pop("CATALOG_ROOT", None)
            else:
                os.environ["CATALOG_ROOT"] = was
        return code, out.getvalue()

    def test_the_file_this_repository_carries_is_the_tools(self):
        with open(os.path.join(os.path.dirname(HERE), "aerieos-releases"), encoding="utf-8") as f:
            text = f.read()
        tags = [ln.split()[0] for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        self.assertEqual(text, self.ar.releases_text(tags))
        self.assertEqual(cc.listed(), tags)

    def test_a_run_with_no_aerieos_named_fails_and_says_so(self):
        self.assertEqual(self.cc.listed(), [])
        code, _ = self.run_check()
        self.assertIn("no AerieOS release is listed yet", str(code))
        self.assertIn("tools/aerieos-release.py TAG", str(code))

    def test_what_only_a_release_can_say_is_said_as_missing(self):
        # Whose alone needs no release, and says that none is listed.
        code, out = self.run_check("--whose-from", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertIn("note  no AerieOS release is listed yet", out)
        self.assertIn("formats does not say which AerieOS first reads pack format 5", out)
        # A signed index is main's, and main is held to the releases it
        # serves: with none listed that is a failure, whatever the signature.
        with open(os.path.join(self.d, "index.sig"), "w", encoding="utf-8") as f:
            f.write("not a signature\n")
        code, out = self.run_check("--whose-from", "HEAD", "--signed")
        self.assertIn("formats does not say which AerieOS first reads it", str(code))
        self.write({**self.index, "formats": {"5": "0.9.0-dev.5700"}})
        code, out = self.run_check("--whose-from", "HEAD", "--signed")
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL  a signed index is held to the releases it serves, and none is listed", out)

    def test_once_a_release_is_listed_the_formats_are_held(self):
        with open(os.path.join(self.d, "aerieos-releases"), "w", encoding="utf-8") as f:
            f.write(self.ar.releases_text(["v0.9.0-dev.5700"]))
        code, _ = self.run_check("--whose-from", "HEAD")
        self.assertIn("formats does not say which AerieOS first reads it", str(code))
        self.write({**self.index, "formats": {"5": "0.9.0-dev.5700"}})
        code, out = self.run_check("--whose-from", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertNotIn("no AerieOS release is listed", out)


class Release(unittest.TestCase):
    """aerieos-release.py: a release listed, and the formats it brought dated."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.ar = load("aerieos-release", self.d)
        # A checkout of an AerieOS that reads pack format 5, as far as the tool reads one.
        self.aerieos = os.path.join(self.d, "aerieos")
        os.makedirs(os.path.join(self.aerieos, "scripts", "dashboard"))
        self.reads(5)
        with open(os.path.join(self.aerieos, "scripts", "dashboard", "catalogentry.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(self.d, "aerieos-releases"), "w", encoding="utf-8") as f:
            f.write(self.ar.releases_text([]))
        self.text = json.dumps({"formats": {"2": "0.9.0"}, "version": 1, "generated": "2026-11-20T00:00:00Z",
                                "packs": [entry("hexkit", format=5, framework="5.2"), entry("plain")]}, indent=1) + "\n"
        with open(os.path.join(self.d, "index.json"), "w", encoding="utf-8") as f:
            f.write(self.text)

    def reads(self, n):
        with open(os.path.join(self.aerieos, "scripts", "dashboard", "packformat.py"), "w", encoding="utf-8") as f:
            f.write(f"FORMAT = {n}\n")

    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                code = self.ar.main([*argv, "--aerieos", self.aerieos])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def now(self):
        with open(os.path.join(self.d, "index.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_the_first_release(self):
        code, out = self.run_tool("v0.9.0-dev.5700")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ar.listed(), ["v0.9.0-dev.5700"])
        # Every format it reads is its: it is the oldest the catalog serves.
        self.assertEqual(self.now()["formats"], {"2": "0.9.0-dev.5700", "3": "0.9.0-dev.5700", "4": "0.9.0-dev.5700", "5": "0.9.0-dev.5700"})
        # Nothing else of the index moved, its date among it: signing stamps that.
        was = json.loads(self.text)
        self.assertEqual({k: v for k, v in self.now().items() if k != "formats"}, {k: v for k, v in was.items() if k != "formats"})
        self.assertIn("needs signing again", out)
        # ...and the file no longer says that none is listed.
        with open(os.path.join(self.d, "aerieos-releases"), encoding="utf-8") as f:
            self.assertNotIn("No release is listed yet", f.read())
        # Run again, it changes nothing.
        before = self.now()
        code, out = self.run_tool("v0.9.0-dev.5700")
        self.assertEqual((code, self.now(), self.ar.listed()), (0, before, ["v0.9.0-dev.5700"]))
        self.assertIn("was listed already", out)

    def test_a_later_release_dates_only_what_it_brought(self):
        self.run_tool("v0.9.0-dev.5700")
        self.reads(6)
        code, out = self.run_tool("v0.10.0")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ar.listed(), ["v0.9.0-dev.5700", "v0.10.0"])
        self.assertEqual(self.now()["formats"], {"2": "0.9.0-dev.5700", "3": "0.9.0-dev.5700", "4": "0.9.0-dev.5700", "5": "0.9.0-dev.5700", "6": "0.10.0"})

    def test_only_takes_the_others_off(self):
        self.run_tool("v0.9.0-dev.5700")
        code, out = self.run_tool("v0.9.0", "--only")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ar.listed(), ["v0.9.0"])
        self.assertIn("v0.9.0-dev.5700 is taken off the list", out)
        self.assertEqual(set(self.now()["formats"].values()), {"0.9.0"})

    def test_a_format_the_release_does_not_read(self):
        self.reads(4)
        code, _ = self.run_tool("v0.9.0-dev.5700")
        self.assertIn("pack format 5, which AerieOS 0.9.0-dev.5700 does not read", str(code))
        self.assertIn("nothing was written", str(code))
        self.assertEqual((self.ar.listed(), json.dumps(self.now(), indent=1) + "\n"), ([], self.text))

    def test_what_is_no_release(self):
        code, _ = self.run_tool("0.9.0")
        self.assertIn("is no release's tag", str(code))
        code, _ = self.run_tool("main")
        self.assertIn("is no release's tag", str(code))
        os.remove(os.path.join(self.aerieos, "scripts", "dashboard", "catalogentry.py"))
        code, _ = self.run_tool("v0.9.0")
        self.assertIn("is not an AerieOS the catalog serves", str(code))
        self.assertEqual(self.ar.listed(), [])


class Whole(unittest.TestCase):
    """What this repository's own index carries is what the rules ask."""

    def test_no_entry_is_open_and_none_says_no_word(self):
        with open(os.path.join(os.path.dirname(HERE), "index.json"), encoding="utf-8") as f:
            d = json.load(f)
        for p in d["packs"]:
            for pin in (p, *(p.get("older") or [])):
                self.assertIn(pin.get("held"), ("pinned", "installer"), p["name"])
                self.assertEqual(pin.get("held") == "installer", "online" in pin, p["name"])
        self.assertEqual(load("catalog-sign").check_index(copy.deepcopy(d), dated=False), [])


if __name__ == "__main__":
    unittest.main()
