"""A pin is on a branch or a tag (catalog-check.py's reachable_from,
here_from, pins_to_hold): a commit a repository merely answers a fetch by
hash for is not that repository's, so a pin is taken only where its commit
is in the history of a branch or a tag of the repository the entry names.

    python3 -m unittest discover -s tools -p 'test_*.py'

The repositories are scratch ones on disk, made here and gone afterwards.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = "https://github.com/aquilaelabs/aerieos-catalog"


def load(root=None):
    """catalog-check.py as a module, reading the catalog at `root`."""
    was = os.environ.get("CATALOG_ROOT")
    if root:
        os.environ["CATALOG_ROOT"] = root
    try:
        spec = importlib.util.spec_from_file_location("catalog_check", os.path.join(HERE, "catalog-check.py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if was is None:
            os.environ.pop("CATALOG_ROOT", None)
        else:
            os.environ["CATALOG_ROOT"] = was


cc = load()


def git(repo, *args):
    r = subprocess.run(["git", "-c", "user.name=Somebody", "-c", "user.email=somebody@example.org", "-c", "commit.gpgsign=false", "-C", repo, *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def commit(repo, text, name="file"):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", text.strip()[:40] or "a change")
    return git(repo, "rev-parse", "HEAD")


class Scratch(unittest.TestCase):
    """A third party's repository on disk: five commits on main, a tag two
    below its tip, and a commit somebody else sent as a pull request, which
    is in the repository's objects under refs/pull/1/head and on no branch
    and no tag, as a forge keeps one."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = os.path.join(self.root, "alice")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        self.on = [commit(self.repo, f"version {n}\n") for n in range(1, 6)]
        git(self.repo, "tag", "-a", "v3", "-m", "the third", self.on[2])
        git(self.repo, "checkout", "-q", "--detach")
        self.sent = commit(self.repo, "somebody else's change\n")
        git(self.repo, "update-ref", "refs/pull/1/head", self.sent)
        git(self.repo, "checkout", "-q", "main")
        self.url = "file://" + self.repo
        was = cc.DEPTHS
        self.addCleanup(setattr, cc, "DEPTHS", was)

    def reach(self, commit_):
        return cc.reachable_from(self.url, commit_, local=True)


class Reachable(Scratch):
    def test_a_commit_on_a_branch_is_taken(self):
        for c in self.on:
            self.assertEqual(self.reach(c), "", c)

    def test_a_commit_a_tag_names_is_taken_where_its_branch_is_gone(self):
        git(self.repo, "checkout", "-q", "-b", "other", self.on[0])
        git(self.repo, "branch", "-q", "-D", "main")
        self.assertEqual(self.reach(self.on[2]), "", "the tag's own commit")
        self.assertEqual(self.reach(self.on[1]), "", "one below the tag")
        self.assertIn("is on no branch and no tag", self.reach(self.on[4]), "above the tag, and its branch is gone")

    def test_a_commit_only_a_pull_request_holds_is_refused(self):
        # It is in the repository's objects, which is all a fetch by hash asks.
        self.assertEqual(git(self.repo, "cat-file", "-t", self.sent), "commit")
        said = self.reach(self.sent)
        self.assertIn(f"its pin {self.sent[:12]} is on no branch and no tag of {self.url}", said)
        self.assertIn("a pin is taken from a branch or a tag of the repository the entry names", said)
        # ...and once its owner merges it, it is the repository's.
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merged", self.sent)
        self.assertEqual(self.reach(self.sent), "")

    def test_a_commit_the_repository_never_had_is_refused(self):
        self.assertIn("is on no branch and no tag", self.reach("f" * 40))

    def test_it_looks_as_deep_as_it_takes(self):
        # One commit of each head at first, then the whole history: the
        # oldest commit is found, and the pull request's still is not.
        cc.DEPTHS = (1,)
        self.assertEqual(self.reach(self.on[0]), "")
        self.assertIn("is on no branch and no tag", self.reach(self.sent))

    def test_a_repository_that_cannot_be_listed_says_nothing_for_the_pin(self):
        said = cc.reachable_from("file://" + os.path.join(self.root, "nowhere"), self.on[0], local=True)
        self.assertIn("could not be listed, so nothing says its pin", said)

    def test_only_an_https_address_is_asked(self):
        for url in (self.url, self.repo, "ext::sh -c true", "--upload-pack=true", "ssh://git@example.org/a/b", "http://example.org/a/b"):
            self.assertIn("is no https address of a repository", cc.reachable_from(url, self.on[0]), url)
        self.assertIn("is no commit's full hash", cc.reachable_from("https://example.org/a/b", "main"))


def entry(name, url, commit_, **more):
    return {"name": name, "url": url, "commit": commit_, "sha256": "0" * 64, "tier": "vetted", "withdrawn": False, **more}


class Held(unittest.TestCase):
    """Which pins a change has to answer for (pins_to_hold)."""

    A, B, C = "a" * 40, "b" * 40, "c" * 40
    URL = "https://github.com/acme/pack"

    def held(self, was, now, every=False):
        return cc.pins_to_hold({"packs": was}, {"packs": now}, every)

    def test_the_pins_that_moved(self):
        was = [entry("acme", self.URL, self.A), entry("other", "https://github.com/other/pack", self.A)]
        self.assertEqual(self.held(was, was), [])
        now = [entry("acme", self.URL, self.B), was[1]]
        self.assertEqual(self.held(was, now), [("acme", self.URL, self.B)])
        # Every pin where the run asks for all of them.
        self.assertEqual(self.held(was, now, every=True), [("acme", self.URL, self.B), ("other", "https://github.com/other/pack", self.A)])

    def test_a_new_entry_and_one_that_comes_back(self):
        new = entry("acme", self.URL, self.A)
        self.assertEqual(self.held([], [new]), [("acme", self.URL, self.A)])
        self.assertEqual(self.held({}, [new]), [("acme", self.URL, self.A)])
        # Withdrawn, it is offered to nobody; offered again, its pin answers.
        gone = dict(new, withdrawn=True)
        self.assertEqual(self.held([new], [gone]), [])
        self.assertEqual(self.held([gone], [new]), [("acme", self.URL, self.A)])

    def test_an_older_pin_is_a_pin(self):
        was = [entry("acme", self.URL, self.A, format=5)]
        now = [entry("acme", self.URL, self.B, format=6, older=[{"format": 5, "commit": self.A, "sha256": "1" * 64}])]
        self.assertEqual(self.held(was, now), [("acme", self.URL, self.B)])
        now[0]["older"][0]["commit"] = self.C
        self.assertEqual(self.held(was, now), [("acme", self.URL, self.B), ("acme", self.URL, self.C)])

    def test_the_same_commit_under_another_address_is_another_pin(self):
        was = [entry("acme", self.URL, self.A)]
        now = [entry("acme", "https://github.com/taker/pack", self.A)]
        self.assertEqual(self.held(was, now), [("acme", "https://github.com/taker/pack", self.A)])

    def test_each_is_said_with_its_entry_and_a_repository_asked_once(self):
        asked = []

        def reach(url, commit_):
            asked.append((url, commit_))
            return "" if commit_ == self.A else f"its pin {commit_[:12]} is on no branch and no tag of {url}"
        pins = [("acme", self.URL, self.A), ("acme-two", self.URL, self.B), ("acme-three", self.URL + "/", self.B), ("kept", SELF, self.C)]
        said = cc.unreachable(pins, reach=reach, here=lambda c: "its pin is not in the history of the branch being checked")
        self.assertEqual(said, [f"acme-two: its pin {'b' * 12} is on no branch and no tag of {self.URL}",
                                f"acme-three: its pin {'b' * 12} is on no branch and no tag of {self.URL}",
                                "kept: its pin is not in the history of the branch being checked"])
        self.assertEqual(asked, [(self.URL, self.A), (self.URL, self.B)])


class Catalog(unittest.TestCase):
    """The catalog itself, a repository on disk: a pack kept in it is pinned
    at a commit of the branch being checked, and the check says so."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        git(self.d, "init", "-q", "-b", "main")
        with open(os.path.join(self.d, "aerieos-releases"), "w", encoding="utf-8") as f:
            f.write("# none listed\n")
        os.makedirs(os.path.join(self.d, "packs", "aerie", "hexkit"))
        self.first = commit(self.d, "{}\n", "packs/aerie/hexkit/bbtool.json")
        self.write(self.first)
        self.base = commit(self.d, "the index pins the pack\n", "note")
        self.cc = load(self.d)

    def write(self, pin):
        e = entry("hexkit", SELF, pin, tier="aerie", path="packs/aerie/hexkit", about="hexkit", platforms=["linux/amd64"], maker="Somebody", held="pinned")
        with open(os.path.join(self.d, "index.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, "formats": {}, "packs": [e]}, indent=1) + "\n")

    def run_check(self, *argv):
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

    def test_a_commit_of_the_branch_is_taken(self):
        self.assertEqual(self.cc.here_from(self.first), "")
        self.assertEqual(self.cc.here_from(self.base), "")
        # Moved to a later commit of the branch: taken, and said as one pin.
        later = commit(self.d, '{"more": 1}\n', "packs/aerie/hexkit/bbtool.json")
        self.write(later)
        commit(self.d, "the index pins the later commit\n", "note")
        code, out = self.run_check("--whose-from", self.base)
        self.assertEqual(code, 0, out)
        self.assertIn(f"== 1 pin(s) held to a branch or a tag of the repository named: the ones that moved since {self.base}", out)

    def test_a_commit_that_is_on_no_branch_here_is_refused(self):
        # A commit this repository holds and the branch does not: another
        # branch's, as a pull request's is on a forge.
        git(self.d, "checkout", "-q", "-b", "elsewhere")
        aside = commit(self.d, '{"evil": 1}\n', "packs/aerie/hexkit/bbtool.json")
        git(self.d, "checkout", "-q", "main")
        self.assertIn("is not in the history of the branch being checked", self.cc.here_from(aside))
        self.write(aside)
        commit(self.d, "the index pins a commit of another branch\n", "note")
        code, out = self.run_check("--whose-from", self.base)
        self.assertEqual(code, 1, out)
        self.assertIn(f"FAIL  hexkit: its pin {aside[:12]} is not in the history of the branch being checked", out)

    def test_a_pin_that_did_not_move_is_asked_only_where_every_pin_is(self):
        # The branch is rewound below the commit the entry pins: nothing
        # moved, so a change is not asked about it, and a run that holds
        # every pin (no index to start from, or --every-pin) is.
        git(self.d, "checkout", "-q", "--orphan", "fresh")
        commit(self.d, "another history\n", "note")
        code, out = self.run_check("--whose-from", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertIn("== 0 pin(s) held", out)
        for argv in (("--whose-from", "HEAD", "--every-pin"),):
            code, out = self.run_check(*argv)
            self.assertEqual(code, 1, out)
            self.assertIn("FAIL  hexkit: its pin", out)


if __name__ == "__main__":
    unittest.main()
