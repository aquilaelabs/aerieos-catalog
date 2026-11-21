"""The workflows, read as text: what each must and must not do, so that a
change to one cannot quietly hand a pull request, a branch or a third
party's pack more than it is given.

    python3 -m unittest discover -s tools -p 'test_*.py'

What only a run on the forge proves (that a pinned commit is the action it
says, that the runner cuts the network) is not here; what a file can say of
itself is.
"""
import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")
NAMES = sorted(os.path.basename(p) for p in glob.glob(os.path.join(WORKFLOWS, "*.yml")))


def text(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return f.read()


def code(name):
    """A workflow's lines that are not comments."""
    return "\n".join(ln for ln in text(name).splitlines() if not ln.lstrip().startswith("#"))


def jobs(name):
    """{job: its lines} of a workflow, comments left out: a job starts at a
    key two spaces in, under `jobs:`."""
    body = code(name).split("\njobs:\n", 1)[1]
    out, at = {}, None
    for ln in body.splitlines():
        m = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", ln)
        if m:
            at = m.group(1)
            out[at] = []
        elif at:
            out[at].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def scripts(name):
    """Every `run:` of a workflow, as the shell is handed it."""
    out, lines, i = [], code(name).splitlines(), 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", lines[i])
        i += 1
        if not m:
            continue
        if m.group(2) not in ("|", ">", "|-", ">-"):
            out.append(m.group(2))
            continue
        block = []
        while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > len(m.group(1))):
            block.append(lines[i])
            i += 1
        out.append("\n".join(block))
    return out


class Sign(unittest.TestCase):
    def test_the_signing_run_holds_every_pin(self):
        ran = [ln for ln in code("sign.yml").splitlines() if "catalog-check.py" in ln and "grep" not in ln]
        self.assertTrue(ran, "the sign workflow runs the check")
        self.assertTrue(any(re.search(r"--every-pin\b", ln) for ln in ran), ran)


class Whose(unittest.TestCase):
    """The ownership rules run from main's copies, on a pull request read as data."""

    def test_the_rules_a_pull_request_is_held_to_are_mains(self):
        whole, j = code("whose.yml"), jobs("whose.yml")
        self.assertRegex(whole, r"\non:\n  pull_request_target:\n")
        self.assertNotRegex(whole, r"\n  pull_request:\n")
        self.assertEqual(sorted(j), ["whose"])
        # A token that reads, and no secret.
        self.assertRegex(whole, r"\npermissions:\n  contents: read\nconcurrency:")
        self.assertNotIn("secrets.", whole)
        self.assertNotRegex(whole, r":\s*write\b")
        # Two checkouts: main's tools, and the pull request's head beside
        # them, neither keeping the token.
        self.assertEqual(whole.count("uses: actions/checkout@"), 2)
        self.assertEqual(whole.count("persist-credentials: false"), 2)
        self.assertRegex(whole, r"ref: main\n\s+path: held\n")
        self.assertRegex(whole, r"ref: refs/pull/\$\{\{ github\.event\.pull_request\.number \}\}/head\n\s+path: pr\n")
        # Nothing of the pull request is run: the one program is main's
        # check, by the runner's python started with no path of its own,
        # reading the pull request's tree as data.
        ran = [ln.strip() for s in scripts("whose.yml") for ln in s.splitlines() if re.search(r"\b(python3?|pip|npm|bash|sh|make)\b", ln)]
        self.assertEqual(len(ran), 1, ran)
        self.assertRegex(ran[0], r'^CATALOG_ROOT="\$\{PWD\}/pr" python3 -I held/tools/catalog-check\.py --whose-from origin/main "\$\{outside\[@\]\}"$')
        for s in scripts("whose.yml"):
            self.assertNotRegex(s, r"(^|[\s\"'=])\.?/?pr/\S*\.(py|sh)|\bsource\b|(^|\s)\. |\beval\b", s)
        self.assertNotRegex(whole, r"uses: \./")
        # The fork's owner is told to the check, from the event.
        self.assertIn('outside=(--outside "${HEAD_OWNER}")', whole)
        self.assertIn("HEAD_OWNER: ${{ github.event.pull_request.head.repo.owner.login }}", whole)
        # ...and the commit read is the one the run was started for.
        self.assertIn('if [ "${got}" != "${HEAD_SHA}" ]; then', whole)

    def test_the_check_workflow_decides_no_ownership(self):
        whole = code("check.yml")
        self.assertNotIn("pull_request_target", whole)
        self.assertNotIn("secrets.", whole)
        self.assertNotIn("--outside", whole)


if __name__ == "__main__":
    unittest.main()
