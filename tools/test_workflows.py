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


class Every(unittest.TestCase):
    """What holds for every workflow."""

    def test_the_workflows_are_the_four(self):
        self.assertEqual(NAMES, ["check.yml", "pins.yml", "sign.yml", "whose.yml"])

    def test_every_action_is_named_by_its_full_commit_with_its_version_beside_it(self):
        seen = 0
        for name in NAMES:
            for ln in code(name).splitlines():
                if not re.match(r"^\s*(- )?uses:", ln):
                    continue
                seen += 1
                self.assertRegex(ln, r"uses: [A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}\s+# v\d+(\.\d+){1,2}, pinned by commit$", f"{name}: {ln.strip()}")
        self.assertGreaterEqual(seen, 10)

    def test_one_action_is_one_commit_everywhere(self):
        at = {}
        for name in NAMES:
            for action, commit in re.findall(r"uses: (\S+)@([0-9a-f]{40})", code(name)):
                at.setdefault(action, set()).add(commit)
        self.assertEqual({a: len(c) for a, c in at.items() if len(c) != 1}, {})

    def test_everything_pip_installs_is_held_to_its_hash_from_a_list_in_this_repository(self):
        seen = 0
        for name in NAMES:
            for ln in code(name).splitlines():
                if not re.search(r"\bpip[\"']?\s+install\b", ln):
                    continue
                seen += 1
                self.assertIn("--require-hashes", ln, f"{name}: {ln.strip()}")
                self.assertIn("--no-deps", ln, f"{name}: {ln.strip()}")
                m = re.search(r"-r (?:held/)?(tools/[a-z-]+requirements\.txt)", ln)
                self.assertTrue(m, f"{name}: {ln.strip()}")
                with open(os.path.join(ROOT, m.group(1)), encoding="utf-8") as f:
                    listed = [r for r in re.split(r"\n(?=\S)", "\n".join(x for x in f.read().splitlines() if not x.startswith("#"))) if r.strip()]
                self.assertTrue(listed, m.group(1))
                for req in listed:
                    self.assertRegex(req, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*\s", req)
                    self.assertIn("--hash=sha256:", req)
        self.assertGreaterEqual(seen, 3)
        # No python but the runner's own: none is fetched by an action.
        self.assertFalse([n for n in NAMES if "setup-python" in code(n)])

    def test_no_script_is_written_from_a_value_of_the_event(self):
        # A value an outsider chooses (a branch's name, a title, an input)
        # reaches a script through env, never by being written into it.
        for name in NAMES:
            for script in scripts(name):
                self.assertNotIn("${{", script, f"{name}: {script[:200]}")
        self.assertGreaterEqual(sum(len(scripts(n)) for n in NAMES), 12)

    def test_a_token_that_can_write_is_given_to_two_jobs_and_no_other(self):
        writers = {}
        for name in NAMES:
            # Every workflow starts from read alone.
            self.assertRegex(code(name), r"\npermissions:\n  contents: read\n(?!  )", name)
            for job, body in jobs(name).items():
                if re.search(r":\s*write\b", body):
                    writers[f"{name}:{job}"] = body
        self.assertEqual(sorted(writers), ["pins.yml:propose", "sign.yml:sign"])
        # Neither runs a program from a pull request, a branch or the
        # network: pins' proposer runs git and gh alone...
        self.assertNotRegex(writers["pins.yml:propose"], r"\b(python3?|pip|npm|uv|bash|sh) ")
        # ...and the signer runs main's copy of one tool, with its library.
        ran = [m.groups() for m in (re.match(r'^\s*(?:[A-Z_]+="[^"]*" )?("?[^\s"]*(?:python3?|pip)"?|"\$\{python\}") (.*)$', ln)
                                    for ln in writers["sign.yml:sign"].splitlines()) if m]
        self.assertEqual(len(ran), 4, ran)
        for prog, args in ran:
            if "pip" in prog:
                self.assertIn("-r held/tools/sign-requirements.txt", args)
            elif prog == "python3":
                self.assertEqual(args, '-m venv "${RUNNER_TEMP}/venv"')
            else:
                self.assertRegex(args, r"^-I held/tools/catalog-sign\.py (sign|verify) ", (prog, args))


class Sign(unittest.TestCase):
    def test_the_signing_run_holds_every_pin(self):
        ran = [ln for ln in code("sign.yml").splitlines() if "catalog-check.py" in ln and "grep" not in ln]
        self.assertTrue(ran, "the sign workflow runs the check")
        self.assertTrue(any(re.search(r"--every-pin\b", ln) for ln in ran), ran)

    def test_the_key_is_handed_to_mains_tools_alone(self):
        whole = code("sign.yml")
        # Nothing of the branch is ever run or installed from: no path into
        # its tools, and every program is main's copy.
        self.assertNotIn("branch/tools", whole)
        self.assertNotRegex(whole, r"tools=|req=")
        for ln in whole.splitlines():
            if re.search(r"\.(py|sh)\b", ln) and "grep" not in ln and "for f in" not in ln:
                self.assertRegex(ln, r"held/tools/[a-z-]+\.(py|sh)\b", ln.strip())
        # The secret is in one job, the one the environment guards.
        with_key = [job for job, body in jobs("sign.yml").items() if "secrets." in body or "environment:" in body]
        self.assertEqual(with_key, ["sign"])
        self.assertIn("environment: sign", jobs("sign.yml")["sign"])
        # ...and a main that lacks the tools ends the run: said, never worked round.
        self.assertIn("the key is handed to main's tools alone", jobs("sign.yml")["check"])
        self.assertIn('if [ "${RAN_FROM}" != refs/heads/main ]; then', jobs("sign.yml")["check"])

    def test_the_job_that_signs_runs_no_third_partys_code(self):
        j = jobs("sign.yml")
        self.assertEqual(sorted(j), ["check", "installs", "sign"])
        # The installs are a job of their own, which the signer waits for
        # and takes nothing from but that it ended well.
        self.assertIn("--installs-only", j["installs"])
        for job in ("check", "sign"):
            for ln in j[job].splitlines():
                if "python" in ln:
                    self.assertNotRegex(ln, r"--run-installs|--installs-only|offline-install\.py", job)
        self.assertNotIn("catalog-check.py", j["sign"])
        self.assertRegex(j["sign"], r"needs: \[check, installs\]")
        self.assertNotIn("needs.installs.outputs", code("sign.yml"))
        self.assertNotIn("outputs:", j["installs"])
        # No job but the signer keeps the token after its checkout.
        for job in ("check", "installs"):
            self.assertEqual(j[job].count("uses: actions/checkout@"), j[job].count("persist-credentials: false"), job)


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
        self.assertRegex(ran[0], r'^CATALOG_ROOT="\$\{PWD\}/pr" python3 -I held/tools/catalog-check\.py --whose-from "\$\{base\}" "\$\{outside\[@\]\}"$')
        # ...against main as the tools were taken from it.
        self.assertIn('base="$(git -C held rev-parse HEAD)"', whole)
        for s in scripts("whose.yml"):
            self.assertNotRegex(s, r"(^|[\s\"'=])\.?/?pr/\S*\.(py|sh)|\bsource\b|(^|\s)\. |\beval\b", s)
        self.assertNotRegex(whole, r"uses: \./")
        # The fork's owner is told to the check, from the event.
        self.assertIn('outside=(--outside "${HEAD_OWNER}")', whole)
        self.assertIn("HEAD_OWNER: ${{ github.event.pull_request.head.repo.owner.login }}", whole)
        # ...and the commit read is the one the run was started for.
        self.assertIn('if [ "${got}" != "${HEAD_SHA}" ]; then', whole)

    def test_the_check_workflow_decides_no_ownership_and_holds_nothing(self):
        whole, j = code("check.yml"), jobs("check.yml")
        self.assertNotIn("pull_request_target", whole)
        self.assertNotIn("secrets.", whole)
        self.assertNotIn("--outside", whole)
        self.assertEqual(whole.count("uses: actions/checkout@"), whole.count("persist-credentials: false"))
        # Two verdicts: the one that reads the entries runs no third
        # party's code, and the installs are a job of their own.
        self.assertEqual(sorted(j), ["index", "installs"])
        self.assertNotRegex(j["index"], r"--run-installs|--installs-only")
        ran = [ln for ln in j["installs"].splitlines() if "catalog-check.py" in ln]
        self.assertTrue(len(ran) == 1 and "--installs-only" in ran[0], ran)
        self.assertNotIn("needs:", j["index"])


if __name__ == "__main__":
    unittest.main()
