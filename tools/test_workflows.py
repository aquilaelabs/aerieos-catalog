"""The workflows, read as text: what each must and must not do, so that a
change to one cannot quietly hand a pull request, a branch or a third
party's pack more than it is given.

    python3 -m unittest discover -s tools -p 'test_*.py'
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS = os.path.join(os.path.dirname(HERE), ".github", "workflows")


def text(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return f.read()


def code(name):
    """A workflow's lines that are not comments."""
    return "\n".join(ln for ln in text(name).splitlines() if not ln.lstrip().startswith("#"))


class Sign(unittest.TestCase):
    def test_the_signing_run_holds_every_pin(self):
        ran = [ln for ln in code("sign.yml").splitlines() if "catalog-check.py" in ln]
        self.assertTrue(ran, "the sign workflow runs the check")
        self.assertTrue(any(re.search(r"--every-pin\b", ln) for ln in ran), ran)


if __name__ == "__main__":
    unittest.main()
