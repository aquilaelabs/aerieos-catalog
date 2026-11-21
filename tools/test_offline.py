"""The install proof (offline-install.py): a pack installed by the installer
of an AerieOS release, driven from a checkout of it, its declared downloads
fetched and held and its steps run with the network cut and no way to root.

    AERIEOS_CHECKOUT=DIR python3 -m unittest discover -s tools -p 'test_*.py'

The installer is AerieOS's own, so these need a checkout of it:
AERIEOS_CHECKOUT names one (tools/aerieos-checkouts.sh makes one of each
release listed), and without it they are skipped. A machine that cannot cut
the network for a step (no network namespace as this account, and none
through sudo) skips the tests that need the cut itself. OFFLINE_CUT_REQUIRED=1
says neither may be missing, which is what the check workflow says: there a
runner with no checkout, or one that could not cut the network, would let
every submission through.

The other tests put a stand-in for `unshare` on the PATH, as AerieOS's own
unit tests of its installer do: it runs a step with CUT=yes and cuts
nothing, so what is driven and in what order is proved on any machine.
"""
import contextlib
import glob
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("offline_install", os.path.join(HERE, "offline-install.py"))
assert spec and spec.loader
oi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oi)

CHECKOUT = os.environ.get("AERIEOS_CHECKOUT", "")
MUST = os.environ.get("OFFLINE_CUT_REQUIRED") == "1"
SENTENCE = "Its installer downloads the rest from its vendor's releases."
# A step that reaches for the network: an address, no name to look up.
REACH = ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 443), 8)"]
# A step that ends well only where it can become root.
ROOT = ["sudo", "-n", "true"]
# A step that ends well only where no program it runs can gain a privilege.
CONFINED = ["sh", "-c", "grep -Eq '^NoNewPrivs:[[:space:]]*1$' /proc/self/status"]


def git(repo, *args):
    r = subprocess.run(["git", "-c", "user.name=Somebody", "-c", "user.email=somebody@example.org", "-c", "commit.gpgsign=false", "-C", repo, *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def product():
    return oi.Product(CHECKOUT)


def here():
    return product().sdkmeta.this_platform()


def really_cuts():
    """Whether this machine cuts the network for a step, by the release's
    own word for it."""
    if not CHECKOUT:
        return False
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "home"))
        os.makedirs(os.path.join(d, "tmp"))
        p = product()
        return p.cuts("probe", d, True) or p.cuts("probe", d, False)
    finally:
        shutil.rmtree(d, ignore_errors=True)


CAN_CUT = really_cuts()


class Confined(unittest.TestCase):
    def test_the_words_set_no_new_privs_on_what_they_start(self):
        said = subprocess.run([*oi.CONFINED, "grep", "NoNewPrivs", "/proc/self/status"], capture_output=True, text=True, check=False)
        self.assertEqual((said.returncode, said.stdout.split()), (0, ["NoNewPrivs:", "1"]), said.stderr)
        # ...and hand on the command's own exit, and its words as they are.
        self.assertEqual(subprocess.run([*oi.CONFINED, "sh", "-c", 'test "$1" = "a b" && exit 7', "sh", "a b"], check=False).returncode, 7)


class Needs(unittest.TestCase):
    def test_what_the_proof_needs_is_here_where_it_must_be(self):
        if MUST:
            self.assertTrue(CHECKOUT, "a checkout of AerieOS must be named (AERIEOS_CHECKOUT): the install proof is its installer's")
            self.assertTrue(CAN_CUT, "this machine must be able to cut the network for a step, and cannot")


@unittest.skipUnless(CHECKOUT, "no checkout of AerieOS is named (AERIEOS_CHECKOUT)")
class Pack(unittest.TestCase):
    """A pack's folder, a file it declares, and a PATH whose `unshare`
    stands in for the cut."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = os.path.join(self.root, "hexkit")
        self.files = os.path.join(self.root, "files")
        self.mark = os.path.join(self.root, "a-step-ran")
        os.makedirs(self.src)
        os.makedirs(self.files)
        with open(os.path.join(self.files, "tool.bin"), "wb") as f:
            f.write(b"the tool itself")
        self.sha = hashlib.sha256(b"the tool itself").hexdigest()
        env = mock.patch.dict(os.environ, {"OFFLINE_INSTALL_FILES": self.files})
        env.start()
        self.addCleanup(env.stop)

    def stand_in(self, cuts=True):
        """A PATH whose unshare runs a step with CUT=yes (or, with `cuts`
        False, refuses, as on a machine that can make no namespace)."""
        d = os.path.join(self.root, "cutbin" if cuts else "nocutbin")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "unshare"), "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in --*) shift ;; *) break ;; esac; done\n[ $# -gt 0 ] || exit 0\nCUT=yes exec "$@"\n'
                    if cuts else "#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(d, "unshare"), 0o755)
        # sudo answers no on the machine that cannot cut, whatever this one's would.
        if not cuts:
            with open(os.path.join(d, "sudo"), "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(d, "sudo"), 0o755)
        patch = mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")})
        patch.start()
        self.addCleanup(patch.stop)

    def declared(self, sha=None, **more):
        return [{"url": oi.STAND_IN + "tool.bin", "sha256": sha or self.sha, "to": "dl/tool.bin", **more}]

    def pack(self, platforms=None, **install):
        m = {"name": "hexkit", "label": "Hexkit", "about": "Looks inside binaries.", "format": 5, "framework": "5.2", "maker": "Hexkit Project",
             "platforms": platforms or [here()], "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
             "verbs": {"dump": {"about": "Dumps a file.", "usage": "FILE", "run": ["{dir}/bin/hexkit"]}}}
        if install:
            m["install"] = install
        with open(os.path.join(self.src, "bbtool.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)
        with open(os.path.join(self.src, "install.sh"), "w", encoding="utf-8") as f:
            f.write('mkdir -p "$1/bin" && cp "$1/dl/tool.bin" "$1/bin/hexkit"\n')
        return self.src

    def steps(self, *more):
        return [["sh", "{dir}/install.sh", "{dir}"], *more]

    def run_pack(self, cut="required"):
        return self.quiet(oi.run, CHECKOUT, self.src, cut)

    def quiet(self, fn, *args):
        """fn(*args), with what it and the installer said kept in self.said."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = fn(*args)
        self.said = out.getvalue()
        return got


class Driven(Pack):
    """What is driven, and in what order: with a stand-in for the cut."""

    def test_a_pack_that_declares_what_it_downloads_installs_behind_the_cut(self):
        self.stand_in()
        # The download is there before a step runs, each step and the
        # verify run behind the cut, and the tool the layout names is made.
        self.pack(fetch=self.declared(), steps=self.steps(["sh", "-c", 'test "$CUT" = yes && test -s {dir}/dl/tool.bin && test "$HOME" != ""']),
                  verify=["sh", "-c", 'test "$CUT" = yes && test -x {dir}/bin/hexkit'])
        self.assertEqual(self.run_pack(), [])
        # In the release's own words: held first, then cut.
        self.assertIn("verified: sha256 matches what hexkit declares for dl/tool.bin", self.said)
        self.assertIn("hexkit declares its downloads: its steps run with no network", self.said)
        self.assertLess(self.said.index("verified: sha256 matches"), self.said.index("its steps run with no network"))
        # The pack's own files are left as they were: the install was a scratch store's.
        self.assertFalse(os.path.exists(os.path.join(self.src, "bin")))

    def test_a_step_that_fails_is_said_in_the_installers_words(self):
        self.stand_in()
        self.pack(fetch=self.declared(), steps=[["sh", "-c", "echo could not get it >&2; exit 7"]])
        bad = self.run_pack()
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("hexkit: its install by AerieOS", bad[0])
        self.assertIn("could not get it", bad[0])
        self.assertIn("a required step failed (it ran with no network", bad[0])
        self.assertIn("install.fetch", bad[0])

    def test_a_download_that_is_not_what_was_declared_stops_it_before_a_step_runs(self):
        self.stand_in()
        self.pack(fetch=self.declared("0" * 64), steps=[["touch", self.mark]])
        bad = self.run_pack()
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("answered a file whose sha256 is " + self.sha, bad[0])
        self.assertIn("declares " + "0" * 64, bad[0])
        self.assertFalse(os.path.exists(self.mark), "nothing of the pack ran")

    def test_a_download_for_another_platform_is_left_out(self):
        self.stand_in()
        other = "linux/arm64" if here() != "linux/arm64" else "linux/amd64"
        rows = [{**self.declared()[0], "platform": here()},
                {"url": oi.STAND_IN + "not-built-for-this-machine.bin", "sha256": "0" * 64, "to": "dl/tool.bin", "platform": other}]
        self.pack(platforms=["linux/amd64", "linux/arm64"], fetch=rows, steps=self.steps(), verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(self.run_pack(), [])
        self.assertIn(f"leaving out dl/tool.bin: it is for {other}", self.said)

    def test_the_version_a_download_says_fills_its_address(self):
        self.stand_in()
        os.makedirs(os.path.join(self.files, "1.2.3"))
        shutil.copy(os.path.join(self.files, "tool.bin"), os.path.join(self.files, "1.2.3", "tool.bin"))
        rows = [{"url": oi.STAND_IN + "{version}/tool.bin", "version": "1.2.3", "sha256": self.sha, "to": "dl/tool.bin"}]
        self.pack(fetch=rows, steps=self.steps(), verify=["test", "-s", "{dir}/bin/hexkit"])
        os.remove(os.path.join(self.files, "tool.bin"))
        self.assertEqual(self.run_pack(), [])

    def test_what_says_it_is_installed_must_be_there(self):
        self.stand_in()
        self.pack(fetch=self.declared(), steps=[["true"]])
        self.assertTrue(any("bin/hexkit, which says it is installed, is not there" in b for b in self.run_pack()))

    def test_a_manifest_the_release_refuses_is_refused_in_its_words(self):
        self.stand_in()
        for row, said in (({**self.declared()[0], "signed": {"sig": oi.STAND_IN + "tool.sig", "keys": "maker.asc"}}, "install.fetch 1 is {url, sha256, to}"),
                          ({"url": oi.STAND_IN + "tool.bin", "to": "dl/tool.bin"}, "install.fetch 1 is {url, sha256, to}"),
                          ({"url": "http://example.com/tool.bin", "sha256": self.sha, "to": "dl/tool.bin"}, "an https address")):
            self.pack(fetch=[row], steps=[["touch", self.mark]])
            bad = self.run_pack()
            self.assertTrue(len(bad) == 1 and "bbtool.json needs fixing" in bad[0] and said in bad[0], bad)
        self.assertFalse(os.path.exists(self.mark))

    def test_an_open_pack_is_not_run(self):
        # Steps that keep the network and say nothing of what they fetch:
        # the catalog holds no such entry, and here they would run with
        # whatever this account may do.
        self.stand_in()
        self.pack(steps=[["touch", self.mark]])
        bad = self.run_pack()
        self.assertTrue(len(bad) == 1 and "hexkit reads open" in bad[0] and "its install was not run" in bad[0], bad)
        self.assertFalse(os.path.exists(self.mark))

    def test_an_installer_that_keeps_the_network_says_so_and_is_confined(self):
        # Its declared download is held all the same; nothing is asked to
        # cut the network, on a machine that could not; and its steps, which
        # keep the network, run with no_new_privs set.
        self.stand_in(cuts=False)
        self.pack(fetch=self.declared(), online=SENTENCE, steps=self.steps(CONFINED), verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(self.run_pack(), [])
        self.assertIn("hexkit keeps the network for its steps, as its entry says: " + SENTENCE, self.said)
        self.assertNotIn("its steps run with no network", self.said)
        self.pack(fetch=self.declared("0" * 64), online=SENTENCE, steps=[["touch", self.mark]])
        bad = self.run_pack()
        self.assertTrue(len(bad) == 1 and "answered a file whose sha256 is" in bad[0], bad)
        self.assertFalse(os.path.exists(self.mark))

    def test_a_machine_that_cannot_cut_the_network(self):
        self.stand_in(cuts=False)
        self.pack(fetch=self.declared(), steps=[["touch", self.mark]])
        bad = self.run_pack("required")
        self.assertTrue(len(bad) == 1 and "cannot cut the network for a step" in bad[0], bad)
        self.assertEqual(self.run_pack("auto"), [], "said, and nothing run, where it is not required")
        self.assertFalse(os.path.exists(self.mark), "a step never runs with the network to prove it needs none")

    def test_a_pack_for_another_machine_or_another_release_line_is_not_run(self):
        self.stand_in()
        self.pack(platforms=["darwin/arm64" if here() != "darwin/arm64" else "linux/amd64"], fetch=[], steps=[["touch", self.mark]])
        self.assertEqual(self.run_pack(), [])
        self.pack(fetch=[], steps=[["touch", self.mark]])
        with open(os.path.join(self.src, "bbtool.json"), encoding="utf-8") as f:
            m = json.load(f)
        with open(os.path.join(self.src, "bbtool.json"), "w", encoding="utf-8") as f:
            json.dump({**m, "works_with": ["0.1"]}, f)
        self.assertEqual(self.run_pack(), [])
        self.assertFalse(os.path.exists(self.mark))

    def test_a_pack_of_its_own_files_alone(self):
        # Nothing of it runs, so nothing needs the cut.
        self.stand_in(cuts=False)
        self.pack()
        os.makedirs(os.path.join(self.src, "bin"))
        with open(os.path.join(self.src, "bin", "hexkit"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho hexkit\n")
        self.assertEqual(self.run_pack(), [])

    def test_a_folder_that_is_no_pack(self):
        bad = oi.run(CHECKOUT, self.files)
        self.assertTrue(len(bad) == 1 and "holds no bbtool.json" in bad[0], bad)


class Entry(Pack):
    """An index entry, installed at the pin this release takes of it."""

    def catalog(self, **install):
        """A catalog on disk that keeps the pack in a folder: (entry, root)."""
        root = os.path.join(self.root, "catalog")
        self.src = os.path.join(root, "packs", "hexkit")
        os.makedirs(self.src)
        self.pack(**install)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
            f.write("beside the pack, and no part of it\n")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "a pack kept here")
        at = git(root, "rev-parse", "HEAD")
        arc = subprocess.run(["git", "-C", root, "archive", "--format=tar", at, "packs/hexkit"], capture_output=True, check=True).stdout
        entry = {"name": "hexkit", "url": oi.SELF[0], "path": "packs/hexkit", "commit": at, "sha256": hashlib.sha256(arc).hexdigest(), "tier": "vetted",
                 "format": 5, "framework": "5.2", "platforms": [here()], "maker": "Hexkit Project", "held": "pinned", "about": "Looks inside binaries."}
        patch = mock.patch.object(oi, "ROOT", root)
        patch.start()
        self.addCleanup(patch.stop)
        return entry

    def test_a_pack_kept_in_a_folder_is_installed_at_its_pin(self):
        self.stand_in()
        entry = self.catalog(fetch=self.declared(), steps=self.steps(["sh", "-c", "test ! -e {dir}/README.md"]), verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(self.quiet(oi.run_entry, CHECKOUT, entry), [])

    def test_an_archive_that_is_not_the_one_the_entry_pins_is_refused(self):
        self.stand_in()
        entry = self.catalog(fetch=self.declared(), steps=[["touch", self.mark]])
        bad = self.quiet(oi.run_entry, CHECKOUT, {**entry, "sha256": "0" * 64})
        self.assertTrue(len(bad) == 1 and "is not what the catalog vetted" in bad[0], bad)
        bad = self.quiet(oi.run_entry, CHECKOUT, {**entry, "commit": "f" * 40})
        self.assertTrue(len(bad) == 1 and "could not fetch" in bad[0], bad)
        self.assertFalse(os.path.exists(self.mark))

    def test_an_entry_this_release_reads_no_pin_of_is_passed_over(self):
        entry = self.catalog(fetch=[], steps=[["touch", self.mark]])
        self.assertEqual(self.quiet(oi.run_entry, CHECKOUT, {**entry, "format": product().packformat.FORMAT + 1}), [])
        self.assertFalse(os.path.exists(self.mark))

    def test_only_an_https_address_or_this_catalog(self):
        entry = self.catalog(fetch=[], steps=[["touch", self.mark]])
        for url in ("file://" + os.path.join(self.root, "catalog"), "ssh://git@example.org/a/b", "ext::sh -c true", ""):
            bad = self.quiet(oi.run_entry, CHECKOUT, {**entry, "url": url})
            self.assertTrue(len(bad) == 1 and "is no https address of a repository" in bad[0], (url, bad))
        self.assertFalse(os.path.exists(self.mark))


class Checked(Entry):
    """The check's own run of the installs (catalog-check.py --installs-only):
    each third party's pack that differs, by each release's installer, in a
    process of its own."""

    def check(self, *argv):
        root = os.path.join(self.root, "catalog")
        was = os.environ.get("CATALOG_ROOT")
        os.environ["CATALOG_ROOT"] = root
        try:
            spec = importlib.util.spec_from_file_location("catalog_check", os.path.join(HERE, "catalog-check.py"))
            assert spec and spec.loader
            cc = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cc)
            # What an install says comes from its own process, on this
            # one's standard output: put aside, and the check's verdict
            # and its own lines are what is read here.
            out = io.StringIO()
            sys.stdout.flush()
            kept = os.dup(1)
            with open(os.devnull, "w", encoding="utf-8") as null:
                os.dup2(null.fileno(), 1)
            try:
                with contextlib.redirect_stdout(out):
                    try:
                        code = cc.main(list(argv))
                    except SystemExit as e:
                        code = e.code
            finally:
                os.dup2(kept, 1)
                os.close(kept)
            return code, out.getvalue()
        finally:
            if was is None:
                os.environ.pop("CATALOG_ROOT", None)
            else:
                os.environ["CATALOG_ROOT"] = was

    def indexed(self, **install):
        entry = self.catalog(**install)
        root = os.path.join(self.root, "catalog")
        with open(os.path.join(root, "aerieos-releases"), "w", encoding="utf-8") as f:
            f.write("# none listed\n")
        with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "formats": {}, "packs": [entry]}, f)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "the index pins the pack")
        return git(root, "rev-parse", "HEAD~1")

    def test_a_pack_that_installs_and_one_that_does_not(self):
        self.stand_in()
        base = self.indexed(fetch=self.declared(), steps=self.steps(), verify=["test", "-s", "{dir}/bin/hexkit"])
        code, out = self.check("--builderbot", f"next={CHECKOUT}", "--whose-from", base, "--installs-only")
        self.assertEqual(code, 0, out)
        self.assertIn("== hexkit installed by AerieOS next's own installer", out)
        self.assertIn("1 install(s) by 1 AerieOS release(s), 0 problem(s)", out)
        # The installs alone: nothing of the entries is read in this run.
        self.assertNotIn("== whose", out)
        self.assertNotIn("== AerieOS next", out)

    def test_one_that_does_not_is_the_runs_failure(self):
        self.stand_in()
        base = self.indexed(fetch=self.declared(), steps=[["false"]])
        code, out = self.check("--builderbot", f"next={CHECKOUT}", "--whose-from", base, "--installs-only")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL  hexkit: its install was not proved by this AerieOS's installer", out)
        self.assertIn("1 install(s) by 1 AerieOS release(s), 1 problem(s)", out)


class Cut(Pack):
    """The cut itself, and no way to root from inside it: on a machine that
    can make one."""

    def setUp(self):
        super().setUp()
        if not CAN_CUT and not MUST:
            self.skipTest("this machine cannot cut the network for a step")

    def test_a_pack_that_declares_what_it_downloads_installs_with_no_network(self):
        self.pack(fetch=self.declared(), steps=self.steps(), verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(self.run_pack(), [])

    def test_a_step_that_reaches_for_the_network_fails(self):
        self.pack(fetch=self.declared(), steps=self.steps(REACH))
        bad = self.run_pack()
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("a required step failed (it ran with no network", bad[0])

    def test_a_step_that_tries_to_become_root_fails(self):
        # The same pack installs with a step that asks for nothing...
        self.pack(fetch=self.declared(), steps=self.steps(CONFINED), verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(self.run_pack(), [])
        # ...and not with one that asks sudo, on a runner whose account has
        # it without a password: nothing inside the cut gains a privilege.
        for step in (ROOT, ["sh", "-c", "sudo -n nsenter -t 1 -n true"]):
            self.pack(fetch=self.declared(), steps=self.steps(step))
            bad = self.run_pack()
            self.assertEqual(len(bad), 1, (step, bad))
            self.assertIn("a required step failed (it ran with no network", bad[0])
        # The verify is behind it too.
        self.pack(fetch=self.declared(), steps=self.steps(), verify=ROOT)
        self.assertEqual(len(self.run_pack()), 1)

    def test_an_installer_that_keeps_the_network_keeps_no_way_to_root(self):
        self.pack(fetch=self.declared(), online=SENTENCE, steps=self.steps(ROOT))
        bad = self.run_pack()
        self.assertTrue(len(bad) == 1 and "a required step failed" in bad[0], bad)


@unittest.skipUnless(CHECKOUT, "no checkout of AerieOS is named (AERIEOS_CHECKOUT)")
class System(Pack):
    """The system packages a manifest names: which are missing and the
    words that install them are the agent's, and they are run as root."""

    def test_the_agents_words_are_run_for_what_is_missing(self):
        self.stand_in()
        said = os.path.join(self.root, "installed")
        tool = os.path.join(self.root, "pkg")
        with open(tool, "w", encoding="utf-8") as f:
            f.write(f'#!/bin/sh\n[ "$1" = has ] && {{ [ "$2" = there-already ]; exit; }}\nshift\necho "$@" >> "{said}"\n')
        os.chmod(tool, 0o755)
        self.pack(fetch=[], steps=[["true"]])
        with open(os.path.join(self.src, "bbtool.json"), encoding="utf-8") as f:
            m = json.load(f)
        m["system"] = {"apt": ["libfoo1", "there-already", "libbar2"]}
        m["layout"] = {"bin": ["bin"]}
        with open(os.path.join(self.src, "bbtool.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)
        p = product()
        with mock.patch.object(p.backends, "pkg_backend", lambda: ("apt", [tool, "has"], [tool, "install"])), mock.patch.object(oi, "root_words", list):
            self.assertEqual(self.run_pack(), [])
            with open(said, encoding="utf-8") as f:
                self.assertEqual(f.read().split(), ["libfoo1", "libbar2"])
            # Where this account is not root and has no sudo: said, and the install goes on.
            os.remove(said)
            with mock.patch.object(oi, "root_words", lambda: None):
                self.assertEqual(self.run_pack(), [])
            self.assertFalse(os.path.exists(said))
        # One that does not install stops it before anything of the pack runs.
        with mock.patch.object(p.backends, "pkg_backend", lambda: ("apt", ["false"], ["false"])), mock.patch.object(oi, "root_words", list):
            self.pack(fetch=[], steps=[["touch", self.mark]])
            with open(os.path.join(self.src, "bbtool.json"), encoding="utf-8") as f:
                m = json.load(f)
            with open(os.path.join(self.src, "bbtool.json"), "w", encoding="utf-8") as f:
                json.dump({**m, "system": {"apt": ["libfoo1"]}}, f)
            bad = self.run_pack()
        self.assertTrue(len(bad) == 1 and "its system packages did not install" in bad[0], bad)
        self.assertFalse(os.path.exists(self.mark))


@unittest.skipUnless(CHECKOUT, "no checkout of AerieOS is named (AERIEOS_CHECKOUT)")
class Kept(unittest.TestCase):
    """What the driver lays out between the controller's half and the
    node's is held to the release's own reading, on the manifests the
    release keeps of pack format 5 (scripts/dashboard/unit/packformat/5):
    a node that reads the driver's layout reads, of each, exactly what the
    release's recipe for that manifest says."""

    def kept(self):
        d = os.path.join(CHECKOUT, "scripts", "dashboard", "unit", "packformat", "5")
        out = []
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            if path.endswith(".bbapp.json"):
                continue
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
            # A person's pack: an official one is AerieOS's own row, which
            # no install fetches as a pack.
            if m.get("tier") != "official":
                out.append((os.path.basename(path), m))
        return out

    def test_a_node_reads_from_the_layout_what_the_recipe_says(self):
        p = product()
        kept = self.kept()
        self.assertGreaterEqual(len(kept), 4, "the release keeps manifests of pack format 5")
        seen = set()
        for fname, doc in kept:
            root = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, root, True)
            src = os.path.join(root, "pack")
            os.makedirs(src)
            with open(os.path.join(src, "bbtool.json"), "w", encoding="utf-8") as f:
                json.dump(doc, f)
            url, commit = oi.repository_of(src, os.path.join(root, "made"))
            looked = oi.look(p, url, commit, "", "", os.path.join(root, "work"))
            self.assertNotIsInstance(looked, str, f"{fname}: {looked}")
            m, held = looked
            kept = oi.keep(p, url, commit, "", "", "vetted", os.path.join(root, "work"))
            self.assertNotIsInstance(kept, str, f"{fname}: {kept}")
            name, node = kept
            # The release's own reading, straight from the manifest.
            clean, errors = p.toolpacks.validate(doc, p.shipped)
            self.assertEqual(errors, [], fname)
            row = p.toolpacks.recipe({"manifest": clean, "url": url, "commit": commit})
            self.assertEqual((m, held["word"]), (clean, p.packformat.held(clean)[0]), fname)
            # What the node's half reads through the layout, as sdk.sh asks it.
            def node_says(*args, name=name, node=node, fname=fname):
                r = subprocess.run(["python3", os.path.join(p.lib, "sdkmeta.py"), *args], env=p.env(node), capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, 0, (fname, args, r.stderr))
                return r.stdout
            self.assertEqual(node_says("declared", name).splitlines(), p.sdkmeta.declared_plan(row), fname)
            for field in ("source.kind", "source.url", "source.commit"):
                self.assertEqual(node_says("field", name, field).strip(), str(row["source"][field.split(".")[1]]), (fname, field))
            self.assertEqual(node_says("argv", name, "source.verify", "dir=/d").split("\0")[:-1] if row["source"].get("verify") else [],
                             [w.replace("{dir}", "/d") for w in row["source"].get("verify") or []], fname)
            # ...and the system packages are the manifest's, by the agent's reading.
            cat = p.agent.read_catalog(node)
            self.assertEqual(next(r for r in cat["toolchains"] if r["name"] == name).get("system"), row.get("system"), fname)
            seen.add((held["word"], bool(clean["fetch"])))
        # The kept ones cover a pinned pack with downloads, one that
        # downloads nothing, and an installer that keeps the network.
        self.assertTrue({("pinned", True), ("pinned", False), ("installer", True)} <= seen, seen)


if __name__ == "__main__":
    unittest.main()
