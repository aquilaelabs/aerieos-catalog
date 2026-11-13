"""The offline install (offline-install.py): a pack's declared downloads
fetched and held to their sha256, and its steps run with the network cut.

    python3 -m unittest discover -s tools -p 'test_*.py'

A machine that cannot cut the network (no network namespace as this account
or through sudo) skips the tests that need it, unless OFFLINE_CUT_REQUIRED=1
says it must be able to, which is what the check workflow says: there a
runner that could not cut it would let every submission through.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("offline_install", os.path.join(HERE, "offline-install.py"))
assert spec and spec.loader
oi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oi)

CAN_CUT = bool(oi.cut_words())
MUST = os.environ.get("OFFLINE_CUT_REQUIRED") == "1"
# A step that reaches for the network: an address, no name to look up.
REACH = ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 443), 8)"]


class Offline(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = os.path.join(self.root, "pack")
        os.makedirs(self.src)
        self.dl = os.path.join(self.root, "tool.bin")
        with open(self.dl, "wb") as f:
            f.write(b"the tool itself")
        self.sha = hashlib.sha256(b"the tool itself").hexdigest()
        os.environ["OFFLINE_FILE_URLS"] = "1"
        self.addCleanup(os.environ.pop, "OFFLINE_FILE_URLS", None)

    def pack(self, **install):
        m = {"name": "hexkit", "format": 3, "platforms": [oi.here()], "install": install, "layout": {"tool": "bin/hexkit"},
             "verbs": {"dump": {"about": "x", "usage": "", "run": ["{dir}/bin/hexkit"]}}}
        with open(os.path.join(self.src, "bbtool.json"), "w") as f:
            json.dump(m, f)
        with open(os.path.join(self.src, "install.sh"), "w") as f:
            f.write('mkdir -p "$1/bin" && cp "$1/dl/tool.bin" "$1/bin/hexkit"\n')
        return self.src

    def declared(self, sha=None):
        return [{"url": f"file://{self.dl}", "sha256": sha or self.sha, "to": "dl/tool.bin"}]

    def test_the_cut_is_real_where_it_must_be(self):
        if MUST:
            self.assertTrue(CAN_CUT, "this machine must be able to cut the network for a step, and cannot")

    @unittest.skipUnless(CAN_CUT or MUST, "this machine cannot cut the network for a step")
    def test_a_pack_that_declares_what_it_downloads_installs_with_no_network(self):
        src = self.pack(fetch=self.declared(), steps=[["sh", "{dir}/install.sh", "{dir}"]], verify=["test", "-s", "{dir}/bin/hexkit"])
        self.assertEqual(oi.run(src), [])
        # The pack's own files are left as they were: the install was a scratch copy's.
        self.assertFalse(os.path.exists(os.path.join(src, "bin")))

    @unittest.skipUnless(CAN_CUT or MUST, "this machine cannot cut the network for a step")
    def test_a_step_that_reaches_for_the_network_fails(self):
        src = self.pack(fetch=self.declared(), steps=[REACH])
        bad = oi.run(src)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("its step 1 failed with no network", bad[0])
        self.assertIn("install.fetch (pack format 3)", bad[0])

    @unittest.skipUnless(CAN_CUT or MUST, "this machine cannot cut the network for a step")
    def test_what_says_it_is_installed_must_be_there(self):
        src = self.pack(fetch=self.declared(), steps=[["true"]])
        self.assertTrue(any("bin/hexkit, which says it is installed, is not there" in b for b in oi.run(src)))

    def test_a_download_that_is_not_what_was_declared_stops_it(self):
        src = self.pack(fetch=self.declared("0" * 64), steps=[["sh", "{dir}/install.sh", "{dir}"]])
        with mock.patch.object(oi, "cut_words", lambda: ["env"]):
            bad = oi.run(src)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("answered a file whose sha256 is " + self.sha, bad[0])
        self.assertIn("the manifest declares " + "0" * 64, bad[0])

    def test_only_https(self):
        src = self.pack(fetch=[{"url": "http://example.com/tool.bin", "sha256": self.sha, "to": "dl/tool.bin"}], steps=[["true"]])
        with mock.patch.object(oi, "cut_words", lambda: ["env"]):
            self.assertTrue(any("is not an https address" in b for b in oi.run(src)))

    def test_a_machine_that_cannot_cut_the_network(self):
        src = self.pack(fetch=self.declared(), steps=[["true"]])
        with mock.patch.object(oi, "cut_words", list):
            bad = oi.run(src, "required")
            self.assertTrue(len(bad) == 1 and "cannot cut the network for a step" in bad[0], bad)
            self.assertEqual(oi.run(src, "auto"), [], "said, and nothing run, where it is not required")

    def test_a_pack_for_another_machine_is_not_run(self):
        src = self.pack(steps=[["false"]])
        with open(os.path.join(src, "bbtool.json")) as f:
            m = json.load(f)
        m["platforms"] = ["darwin/arm64" if oi.here() != "darwin/arm64" else "linux/amd64"]
        with open(os.path.join(src, "bbtool.json"), "w") as f:
            json.dump(m, f)
        self.assertEqual(oi.run(src), [])
        self.assertTrue(oi.for_here([oi.here().split("/")[0] + "/*"]) and not oi.for_here(["plan9/*"]) and not oi.for_here([]))

    def test_a_pack_of_its_own_files_alone(self):
        src = self.pack()
        self.assertEqual(oi.run(src), [])

    def test_the_steps_run_as_written_with_the_pack_as_dir(self):
        # The orchestration, with a stand-in for the cut: the download lands
        # where the manifest says, each step runs in turn, the verify last.
        src = self.pack(fetch=self.declared(), steps=[["sh", "{dir}/install.sh", "{dir}"], ["sh", "-c", "test \"$HOME\" != \"\" && test -s {dir}/bin/hexkit"]],
                        verify=["test", "-x", "{dir}/bin/hexkit"])
        with mock.patch.object(oi, "cut_words", lambda: ["env"]):
            self.assertEqual(oi.run(src), [])
        src = self.pack(fetch=self.declared(), steps=[["sh", "-c", "echo could not get it >&2; exit 7"]])
        with mock.patch.object(oi, "cut_words", lambda: ["env"]):
            bad = oi.run(src)
        self.assertTrue(len(bad) == 1 and "(exit 7): could not get it" in bad[0], bad)


if __name__ == "__main__":
    unittest.main()
