#!/usr/bin/env python3
"""An AerieOS release listed as one the catalog serves.

    tools/aerieos-release.py TAG [--aerieos DIR] [--only]

A maintainer runs this once the release TAG (v0.9.0-dev.5700, v0.9.0) is
out. It does the two things only a release's version can:

  - aerieos-releases lists TAG, after the releases it already lists. Every
    entry is from then on held to that release, and nothing an install of
    it could take is taken away (tools/catalog-check.py).
  - index.json's formats says which AerieOS first reads each pack format
    past the first: every format TAG reads that no listed release was
    named for yet is dated TAG's version, which is what a card on an older
    install names as what it needs. Each release so dates the formats it
    brought, whether an entry is written in them yet or not, and an entry
    that arrives later in one of them needs nothing more.

The pack format TAG reads is read from AerieOS itself, at TAG: a checkout
tools/aerieos-checkouts.sh makes, or DIR where one is named (taken as TAG's
on the word of whoever names it). A format the index uses that TAG does not
read is said, and nothing is written.

--only takes every other release off the list: TAG is then the oldest the
catalog serves, and every format it reads is dated to it. Taking a release
off ends the promise to its installs, so it is asked for by name.

Nothing here signs. index.json changes (formats), so the index needs the
maintainers' signing run afterwards: the sign workflow, for the branch this
was run on, and then the merge.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CATALOG_ROOT") or os.path.dirname(HERE)
RELEASES, INDEX = os.path.join(ROOT, "aerieos-releases"), os.path.join(ROOT, "index.json")
TAG = re.compile(r"v\d{1,4}\.\d{1,4}\.\d{1,4}(-[0-9A-Za-z]+(\.[0-9A-Za-z]+){0,3})?")

# What aerieos-releases says above the releases it lists, written here so
# the file and the tool cannot drift.
HEADER = """\
# The AerieOS releases the catalog serves, one tag a line, oldest first.
# Every entry is held to each of these that reads a pin of it
# (tools/catalog-check.py): the oldest install that takes an entry must take
# it as the newest does, and nothing an install of a listed release could
# take is taken away from it. A release is listed by tools/aerieos-release.py
# TAG once it is out; one no longer served is taken off, and with it the
# promise to its installs and the older pins only it needed.
"""
NONE_YET = """\
#
# No release is listed yet. The catalog holds every download to something
# its entry carries, in pack format 5, and the first AerieOS that reads that
# is the oldest the catalog will ever serve: the releases before it are gone
# from this list and nothing is owed to them. When that release is out:
#
#     tools/aerieos-release.py TAG
#
# lists it here and writes into index.json which AerieOS first reads each
# pack format (formats). Until then every tool and workflow that needs a
# release says that none is listed, and none of them passes for want of one.
"""


def listed():
    """The releases aerieos-releases lists, oldest first."""
    try:
        with open(RELEASES, encoding="utf-8") as f:
            return [ln.split()[0] for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def releases_text(tags):
    """aerieos-releases as it is written for these releases."""
    return HEADER + ("".join(f"{t}\n" for t in tags) if tags else NONE_YET)


def checkout_of(tag):
    """Where tools/aerieos-checkouts.sh keeps AerieOS at `tag`, fetched
    there if it was not, or an exit that says why it could not be."""
    r = subprocess.run([os.path.join(HERE, "aerieos-checkouts.sh"), "--only", tag], capture_output=True, text=True, check=False)
    words = r.stdout.split()
    if r.returncode != 0 or len(words) != 2 or not words[1].startswith(tag + "="):
        sys.exit(f"AerieOS could not be fetched at {tag}: {(r.stderr.strip().splitlines() or ['no checkout was made'])[-1]}")
    return words[1].partition("=")[2]


def reads(checkout):
    """The newest pack format the AerieOS in `checkout` reads."""
    dash = os.path.join(checkout, "scripts", "dashboard")
    if not os.path.isfile(os.path.join(dash, "catalogentry.py")):
        sys.exit(f"{checkout} is not an AerieOS the catalog serves: it has no scripts/dashboard/catalogentry.py, so it is from before "
                 "an entry said what its downloads are held to")
    # Read and nothing more: no bytecode is left behind in the checkout.
    r = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import packformat; print(int(packformat.FORMAT))", dash],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        sys.exit(f"the pack format {checkout} reads could not be read: {(r.stderr.strip().splitlines() or ['it said nothing'])[-1]}")
    return int(r.stdout.strip())


def used(d):
    """The pack formats past the first an index's entries are written in,
    their older pins among them."""
    out = set()
    for p in d.get("packs") or []:
        for pin in (p, *(p.get("older") or [])) if isinstance(p, dict) else ():
            fmt = pin.get("format", 1) if isinstance(pin, dict) else 1
            if isinstance(fmt, int) and not isinstance(fmt, bool) and fmt > 1:
                out.add(fmt)
    return sorted(out)


def dated(d, version, newest, alone):
    """(formats, said, refused): the index's formats with every format
    `version` is the first listed release to read dated to it, what that
    changed in a line each, and the formats the index uses that it does not
    read and nothing dates. `newest` is the newest pack format that release
    reads; `alone` says it is the only release listed, so every format it
    reads is its, whatever a release no longer listed was named for."""
    since = dict(d.get("formats") or {}) if isinstance(d.get("formats"), dict) else {}
    said, refused = [], []
    for fmt in sorted({*range(2, newest + 1), *used(d)}):
        was = since.get(str(fmt))
        if fmt > newest:
            if was is None:
                refused.append(fmt)
            continue
        if was is None or (alone and was != version):
            since[str(fmt)] = version
            said.append(f"pack format {fmt} is first read by AerieOS {version}" + (f" (it said {was})" if was else ""))
    return {k: since[k] for k in sorted(since, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0))}, said, refused


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tag", metavar="TAG")
    ap.add_argument("--aerieos", default="", metavar="DIR", help="a checkout of AerieOS at TAG, in the place of one fetched here")
    ap.add_argument("--only", action="store_true", help="take every other release off the list")
    a = ap.parse_args(argv)
    if not TAG.fullmatch(a.tag):
        sys.exit(f"{a.tag} is no release's tag: v0.9.0, v0.9.0-dev.5700")
    version = a.tag[1:]
    if a.aerieos:
        print(f"reading AerieOS in {a.aerieos}, which you say is {a.tag}")
    newest = reads(a.aerieos or checkout_of(a.tag))
    try:
        with open(INDEX, encoding="utf-8") as f:
            text = f.read()
        d = json.loads(text)
    except (OSError, ValueError) as e:
        sys.exit(f"index.json could not be read: {e}")
    was = listed()
    tags = [a.tag] if a.only else [*(t for t in was if t != a.tag), a.tag]
    formats, said, refused = dated(d, version, newest, alone=tags == [a.tag])
    if refused:
        sys.exit(f"the index has entries in pack format {', '.join(map(str, refused))}, which AerieOS {version} does not read (it reads up to "
                 f"{newest}) and no listed release is named for: nothing was written")
    for t in was:
        if t not in tags:
            print(f"{t} is taken off the list: the catalog no longer serves it")
    print(f"{a.tag} is listed" if a.tag not in was else f"{a.tag} was listed already")
    with open(RELEASES, "w", encoding="utf-8") as f:
        f.write(releases_text(tags))
    for ln in said:
        print(ln)
    if formats != d.get("formats"):
        # Written as the index is laid out: its other keys, then the
        # entries, with only formats changed.
        new = {"formats": formats, **{k: v for k, v in d.items() if k != "formats"}}
        with open(INDEX, "w", encoding="utf-8") as f:
            f.write(json.dumps(new, indent=1) + "\n")
        print("index.json's formats is written: the index needs signing again (the sign workflow, for this branch), then the merge")
    else:
        print("index.json's formats already said so: nothing of the index changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
