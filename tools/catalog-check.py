#!/usr/bin/env python3
"""The vetting check: what CI runs on every pull request and every push,
before a maintainer reviews an entry and signs the index.

    tools/catalog-check.py --builderbot [NAME=]DIR ... [--changed-from REF] [--whose-from REF] [--outside OWNER] [--every-pin] [--run-installs] [--signed]

DIR is a checkout of AerieOS, whose own readers are the ones used, so an
entry passes here exactly when an install would take it. Named more than
once, each is a release still supported (aerieos-releases lists them), and
an entry is held to every one that reads a pin of it: the oldest install
that takes it must take it as the newest does.

Each entry is read as an install reads it. A release takes the newest pin
of an entry whose pack format it reads (AerieOS's packformat.pin_for: the
entry's own, or one of its older pins), and that pin is held to the folder
at ITS commit through the reader an install uses (catalogentry.differs):
the commit is the one answered, the sha256 of its archive (of its folder,
with a path) is the one the pin names, its manifest passes AerieOS's
validator (a pack's bbtool.json, an app's bbapp.json and compose.yml), and
everything the entry repeats of that manifest is what the manifest says:
its pack format, the framework's version, its platforms, its label, the
release lines it works with, what its downloads are held to, a recipe's
rev, its name, its kind and who it is by. An entry's older pins are held to
their shape (packformat.older_refused), and each is checked the same way by
every release named here that reads its format. A release that reads no
pin of an entry passes it over, as an install of it lists nothing; an
entry no release named here reads is a failure, since nobody could install
it, and so is one whose newest pin none of them reads, since nothing
checked it. A withdrawn entry is held to the shape alone.

No entry is open. What an entry fetches from somewhere else is held to
something the entry itself carries, and its manifest reads pinned or
installer by AerieOS's own word for it (packformat.held, an app's by its
images). One that reads open, or whose entry says no word, is refused with
the entry named and the reason.

Nothing is taken away from a release. With --changed-from REF (or
--whose-from REF), an entry a release named here could take at REF (a pin
it reads, the entry not withdrawn) still answers that release a pin now,
or is marked withdrawn:
a pack that moves to a newer pack format keeps its older pin, and that pin
goes only once no listed release needs it.

--changed-from REF fetches only the entries that differ from the index at
REF (a pull request's base); --signed also checks index.sig against
catalog.pub, which is what a push to main must carry.

Whose an entry is. An entry at tier official or aerie is this repository's
own; any other is a third party's, its owner the account its repository is
under. --changed-from REF (and --whose-from REF, which fetches nothing less)
says whose each entry is that differs from the index at REF, and refuses a
change that crosses owners: Aerie's own entries and a third party's in one
change, two owners' entries in one change, a third party's entry removed
(one found wanting is withdrawn), handed to another owner, or changed with
no new pin beyond what is the maintainers' to say (withdrawn and tier) and
what their tools write from the manifest and this check verifies (held,
online, older and the format fields), and anything else of this repository
changed beside a third party's entry. --outside OWNER says the change comes
from outside this repository, a pull request from OWNER's fork: it adds its
entry, or moves one whose repository is under OWNER's own account, and never
moves one of Aerie's or changes a file that was here. An entry under any
other account (an organization's, moved by one of its members, is that) is
moved by a maintainer on a branch of the catalog, after hearing from its
owner. The files it adds are its new pack's, in a new folder of that
entry's own: nothing is added to a folder that was here.

A pin is on a branch or a tag. A forge answers a fetch by hash for commits
that are on no branch of the repository asked: a pull request's against it,
a fork's. So a commit that is merely fetchable under an address is not that
repository's, and a pin is taken only where its commit is in the history of
a branch or a tag of the repository the entry names (reachable_from: the
heads and the tags listed, fetched without their files as deep as it takes
to answer). A pack kept in this repository is pinned at a commit of the
branch being checked. With --changed-from or --whose-from the pins that
moved are held to this; with neither, or with --every-pin (the signing run),
every pin is.

--run-installs installs each third party's pack that differs, the way a
node would, with no network beyond the downloads its manifest declares
(install.fetch, each held to its sha256 or its publisher's signature;
offline-install.py): a pack whose install reaches for anything it did not
declare fails here. So work on Aerie's own packs, by a person, a session
or tools/packs-export.py, can never carry a third party's entry along, and
a submission can never reach past its own.

aerieos-releases lists the releases the catalog serves. While it lists
none, nothing here passes for want of one: a run that names no checkout
says so and fails, and what only a release's version can say (the index's
formats) is said as missing until tools/aerieos-release.py TAG writes it.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The catalog this checks: the one this file is in, or CATALOG_ROOT's, which
# is how a pull request is held to the copy of this file main has (the
# check workflow), so that it cannot loosen the rule it is held to.
ROOT = os.environ.get("CATALOG_ROOT") or os.path.dirname(HERE)
INDEX = os.path.join(ROOT, "index.json")
# This repository, by its name and by the one it had before: an entry
# pinned under either is this repository's own.
SELF = ("https://github.com/aquilaelabs/aerieos-catalog", "https://github.com/aquilaelabs/builderbot-catalog")
OWN = ("packs/official/", "packs/agents/", "packs/services/")
RELEASES = os.path.join(ROOT, "aerieos-releases")
NO_RELEASE = ("no AerieOS release is listed yet (aerieos-releases): name the first with tools/aerieos-release.py TAG once it is out, "
              "or a checkout of the AerieOS to hold the entries to with --builderbot NAME=DIR")


def listed():
    """The AerieOS releases aerieos-releases lists, oldest first: one tag a
    line, a # line a comment."""
    try:
        with open(RELEASES, encoding="utf-8") as f:
            return [ln.split()[0] for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def index_at(ref):
    """The index as `ref` has it, {} where it has none."""
    r = subprocess.run(["git", "-C", ROOT, "show", f"{ref}:index.json"], capture_output=True, text=True, check=False)
    try:
        d = json.loads(r.stdout) if r.returncode == 0 else {}
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def changed(packs, ref):
    """The entries that differ from the index at `ref` in anything they
    say: a maker or a tier changed alone is held to its manifest too."""
    before = {p.get("name"): p for p in index_at(ref).get("packs", []) if isinstance(p, dict)}
    return [p for p in packs if before.get(p.get("name")) != p]


# ---- whose an entry is ------------------------------------------------------
# What never changes on a third party's entry, and what changes with no new
# pin: the two things that are the maintainers' to say about it.
LOCKED = ("url", "kind")
MAINTAINERS = ("withdrawn", "tier")
# ...and what the maintainers' tools write from the manifest at the pin, and
# this check holds to that manifest (catalogentry.differs, older_refused):
# what the entry's downloads are held to, its older pins and the format
# fields. A rewrite of them changes nothing the pin does not say, so it is
# not a third party's entry changed with no new pin.
WRITTEN = ("held", "online", "older", "format", "framework")
# What a change that moves a third party's entry may change beside the
# index: the signature the maintainers' workflow commits to its branch.
BESIDE = ("index.json", "index.sig")


def owner_of(p):
    """Whose an entry is: "" for this repository's own (official, aerie),
    else the account its repository is under (https://host/account/), or
    its folder for a submission kept in this repository."""
    if p.get("tier") in ("official", "aerie"):
        return ""
    url = str(p.get("url") or "").rstrip("/")
    if url in SELF:
        return "this repository's " + (str(p.get("path") or "").strip("/") or "packs")
    parts = url.split("/")
    return "/".join(parts[:4]) + "/" if len(parts) >= 4 else url


# The forge this repository is on: an account that sends a change from
# outside is one of its accounts, and owns the repositories under its name
# there and nowhere else.
FORGE = "/".join(SELF[0].split("/")[:3]) + "/"
ACCOUNT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
# A folder a submission's pack is kept in here: plain names under packs/.
FOLDER = re.compile(r"packs(/[a-z0-9][A-Za-z0-9._-]{0,79}){1,3}")


def whose(before, after, files=(), outside=False, added=(), account="", existed=None):
    """(lines, problems): whose each entry is that differs between two
    indexes, and every way the change crosses owners. `files` is what else
    the change touches in this repository, `added` those of them that are
    new; `outside` says the change comes from outside this repository (a
    pull request from a fork), which never moves what was here, and
    `account` whose fork that is. `existed(folder)` answers whether a
    folder was here before the change."""
    was = {p.get("name"): p for p in before.get("packs", []) if isinstance(p, dict)}
    now = {p.get("name"): p for p in after.get("packs", []) if isinstance(p, dict)}
    account = account if isinstance(account, str) and ACCOUNT.fullmatch(account) else ""
    lines, bad, ours, theirs, folders = [], [], [], {}, []
    for name in sorted(set(was) | set(now), key=str):
        a, b = was.get(name), now.get(name)
        if a == b:
            continue
        who = owner_of(b if b is not None else a)
        if a is not None and b is not None and owner_of(a) != who:
            bad.append(f"{name} changes hands, from {owner_of(a) or 'Aerie'} to {who or 'Aerie'}: an entry stays its owner's")
            who = owner_of(a) or who
        (theirs.setdefault(who, []) if who else ours).append(name)
        if b is None:
            lines.append(f"whose {name}: {who or 'Aerie'}'s, removed")
            if who:
                bad.append(f"{name} is removed: a third party's entry found wanting is withdrawn (withdrawn: true), never removed")
            continue
        if who and str(b.get("url") or "").rstrip("/") in SELF:
            folders.append(str(b.get("path") or "").strip("/") + "/")
        if a is None:
            lines.append(f"whose {name}: {who or 'Aerie'}'s, added at {str(b.get('commit'))[:12]}")
            continue
        fields = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        moved = "commit" in fields
        lines.append(f"whose {name}: {who or 'Aerie'}'s, " + (f"pin moved {str(a.get('commit'))[:12]} to {str(b.get('commit'))[:12]}" if moved else "no new pin")
                     + f", changes {', '.join(fields)}")
        if not who:
            continue
        locked = [k for k in fields if k in LOCKED]
        if locked:
            bad.append(f"{name}: a third party's entry never changes its {' or its '.join(locked)}: a pack that moved is a new entry, and the old one is withdrawn")
        loose = [k for k in fields if k not in MAINTAINERS and k not in LOCKED and k not in WRITTEN]
        if loose and not moved:
            bad.append(f"{name}: {', '.join(loose)} changed with no new pin: what a third party's entry says changes only with the commit it pins "
                       "(withdrawn and tier are the maintainers' to change, and held, online, older and the format fields are written from its manifest)")
    if outside:
        for name in ours:
            if name in was:
                bad.append(f"{name} is Aerie's own: a change from outside this repository never moves it")
            else:
                bad.append(f"{name} is added at tier {now[name].get('tier')}: a submission is added as vetted, and the maintainers say the rest")
        # An entry that was here is moved from outside by the account its
        # repository is under, and by nobody else: an address says whose a
        # repository is, never who sends a change.
        whom = f"{account}'s fork" if account else "a fork whose owner the check was not told"
        for who, names in sorted(theirs.items()):
            for name in names:
                if name not in was or name not in now:
                    continue
                if who.startswith("this repository's "):
                    bad.append(f"{name} is kept in this repository, where no account outside owns it: a maintainer moves it on a branch of the catalog "
                               "after hearing from its owner")
                elif not account or who.lower() != (FORGE + account + "/").lower():
                    bad.append(f"{name}'s repository is under {who} and this change comes from {whom}: from outside, an entry is moved only from "
                               "the fork of the account its repository is under, and for anybody else (a member of an organization the repository "
                               "is under, an owner on another forge) a maintainer moves it on a branch of the catalog after hearing from its owner")
        # ...and the files it adds are its new pack's, in the folder of an
        # entry this change adds, new with it: nothing is added to a folder
        # that was here, an entry's or not, since a folder pack's files are
        # its archive at the next pin.
        had = [str(p.get("path") or "").strip("/") + "/" for p in was.values() if str(p.get("url") or "").rstrip("/") in SELF and p.get("path")]
        new = []
        for name in sorted((n for n in now if n not in was), key=str):
            b = now[name]
            if not owner_of(b) or str(b.get("url") or "").rstrip("/") not in SELF:
                continue
            path = str(b.get("path") or "").strip("/")
            d = path + "/"
            if not FOLDER.fullmatch(path):
                bad.append(f"{name} is kept in {path or 'no folder'}: a submission kept in this repository is in a folder of its own under packs/")
            elif any(d.startswith(f) or f.startswith(d) for f in had) or (existed(d) if existed else False):
                bad.append(f"{name} is kept in {path}, which was here before this change or is inside another pack's folder: a submission kept in "
                           "this repository comes in a new folder of its own")
            else:
                new.append(d)
        held = sorted(f for f in files if f != "index.json" and not (f in added and any(f.startswith(d) for d in new)))
        if held:
            bad.append(f"{', '.join(held[:8])}{'...' if len(held) > 8 else ''}: a change from outside this repository adds its entry to index.json, "
                       "and its new pack's files in a new folder of that entry's own under packs/ where the pack is kept here: it changes nothing "
                       "that was here and adds nothing to a folder that was (index.sig is the maintainers')")
    if ours and theirs:
        bad.append(f"this change moves Aerie's own entries ({', '.join(ours[:6])}{'...' if len(ours) > 6 else ''}) and a third party's "
                   f"({', '.join(n for v in theirs.values() for n in v)}): one or the other, never both")
    if len(theirs) > 1:
        bad.append("this change moves entries of more than one owner (" + "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(theirs.items()))
                   + "): one owner's entries to a change")
    if theirs:
        for k in ("version", "formats"):
            if before.get(k) != after.get(k):
                bad.append(f"the index's {k} changed beside a third party's entry: that is this repository's own, in a change of its own")
        beside = sorted(f for f in files if f not in BESIDE and not any(f.startswith(d) for d in folders if d != "/"))
        if beside:
            bad.append(f"{', '.join(beside[:8])}{'...' if len(beside) > 8 else ''} changed beside a third party's entry: "
                       "such a change is the entry in index.json, and its own folder where the pack is kept here, alone")
    return lines, bad


# ---- a pin is on a branch or a tag ------------------------------------------
# An address a repository is listed and fetched at for this: https alone. A
# test names a repository on disk, and says so.
ADDRESS = re.compile(r"https://[A-Za-z0-9._~:/@+-]{3,300}")
# How deep the heads and the tags are fetched, in turn, before the whole
# history is: most pins are near a tip.
DEPTHS = (64, 1024)
GIT_TIMEOUT = 600


def _git(args, cwd=None, local=False):
    """git, asked about a third party's repository: over https alone (a
    file on disk for a test that says so), nobody prompted, nothing fetched
    that was not asked for. The finished process, or None where it could
    not be run or did not end."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="https:file" if local else "https", GIT_NO_LAZY_FETCH="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def reachable_from(url, commit, local=False):
    """Why `commit` is not taken as a commit of the repository at `url`, or
    "": it is in the history of one of that repository's branches or tags.
    A commit a forge merely answers a fetch by hash for (a pull request's
    against the repository, a fork's) is on none of them. The heads and the
    tags are listed first, which answers for a pin at a tip with nothing
    fetched; else they are fetched without their files, a little deeper
    each time, into a scratch repository that is gone when this returns.
    `local` is a test's: its repository is one on disk."""
    import shutil
    import tempfile
    short = commit[:12]
    if not (ADDRESS.fullmatch(url) or (local and url.startswith("file:///"))):
        return f"{url} is no https address of a repository, so nothing says its pin {short} is on a branch or a tag of it"
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return f"{commit[:40]} is no commit's full hash"
    listed_ = _git(["ls-remote", "--heads", "--tags", "--", url], local=local)
    if listed_ is None or listed_.returncode != 0:
        said = ((listed_.stderr or listed_.stdout).strip().splitlines() if listed_ else []) or ["git did not answer"]
        return f"the branches and tags of {url} could not be listed, so nothing says its pin {short} is on one: {said[-1]}"
    tips = {ln.split("\t", 1)[0] for ln in listed_.stdout.splitlines() if "\t" in ln}
    if commit in tips:
        return ""
    no = (f"its pin {short} is on no branch and no tag of {url}: a commit that address only answers a fetch by hash for (a pull request's, "
          "a fork's) is not that repository's, and a pin is taken from a branch or a tag of the repository the entry names")
    if not tips:
        return no
    work = tempfile.mkdtemp(prefix="catalog-reach.")
    try:
        made = _git(["init", "-q", "--bare", work])
        if made is None or made.returncode != 0:
            return f"no scratch repository could be made to look for {short} in, so nothing says it is on a branch or a tag of {url}"
        specs = ["+refs/heads/*:refs/reach/heads/*", "+refs/tags/*:refs/reach/tags/*"]
        for depth in (*DEPTHS, 0):
            deep = [f"--depth={depth}"] if depth else (["--unshallow"] if os.path.isfile(os.path.join(work, "shallow")) else [])
            got = _git(["-C", work, "fetch", "-q", "--no-tags", "--no-recurse-submodules", "--filter=tree:0", *deep, "--", url, *specs], local=local)
            if got is None or got.returncode != 0:
                said = ((got.stderr or got.stdout).strip().splitlines() if got else []) or ["git did not answer"]
                return f"the branches and tags of {url} could not be fetched, so nothing says its pin {short} is on one: {said[-1]}"
            # In the history of a head or a tag that was fetched, and not
            # only among the objects: asked of the refs themselves.
            on = _git(["-C", work, "for-each-ref", "--count=1", "--contains", commit, "refs/reach/"])
            if on is not None and on.returncode == 0 and on.stdout.strip():
                return ""
            if not os.path.isfile(os.path.join(work, "shallow")):
                break
        return no
    finally:
        shutil.rmtree(work, ignore_errors=True)


def here_from(commit):
    """Why `commit` is not taken as the pin of a pack kept in this
    repository, or "": it is in the history of the branch being checked."""
    r = subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", commit, "HEAD"], capture_output=True, text=True, check=False)
    if r.returncode == 0:
        return ""
    return (f"its pin {commit[:12]} is not in the history of the branch being checked: a pack kept in this repository is pinned at a commit "
            "of the branch that carries its entry")


def pins_of(p):
    """The commits an entry pins: its own, and each older pin's."""
    older = p.get("older") if isinstance(p.get("older"), list) else []
    return [str(pin.get("commit") or "") for pin in (p, *older) if isinstance(pin, dict)]


def pins_to_hold(before, after, every=False):
    """[(name, url, commit)]: the pins of `after`'s entries that are held to
    a branch or a tag. Every pin of every entry that is offered with
    `every`; else the ones that moved: a commit the entry did not pin at
    `before`, or pins under another address, or at an entry that was not
    offered there (new, or withdrawn then). A withdrawn entry is offered to
    nobody and is passed over."""
    was = {p.get("name"): p for p in before.get("packs", []) if isinstance(p, dict)} if isinstance(before, dict) else {}
    out = []
    for p in after.get("packs", []):
        if not isinstance(p, dict) or p.get("withdrawn") is True:
            continue
        a = was.get(p.get("name"))
        had = set() if every or a is None or a.get("withdrawn") is True or a.get("url") != p.get("url") else set(pins_of(a))
        out += [(p.get("name"), str(p.get("url") or ""), c) for c in pins_of(p) if c not in had]
    return out


def unreachable(pins, reach=reachable_from, here=here_from):
    """What is wrong with each of `pins` (pins_to_hold) as a commit of the
    repository its entry names: a sentence each, the entry named. A
    repository is asked once for each commit, whatever number of entries
    pin it."""
    said, known = [], {}
    for name, url, commit in pins:
        key = (url.rstrip("/"), commit)
        if key not in known:
            known[key] = here(commit) if key[0] in SELF else reach(url, commit)
        if known[key]:
            said.append(f"{name}: {known[key]}")
    return said


def fork_of(ref):
    """Where this checkout left `ref`: their merge base, so what `ref` has
    gained since is not read as this change's. `ref` itself where git
    names none (a shallow checkout, a ref of another history)."""
    r = subprocess.run(["git", "-C", ROOT, "merge-base", ref, "HEAD"], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ref


def installs_offline(p):
    """What is wrong with a third party's pack installed with no network
    beyond the downloads it declares (offline-install.py), [] when it goes
    through: its files taken at the commit the entry pins, then run."""
    import shutil
    import tempfile
    offline = _load(os.path.join(HERE, "offline-install.py"), "offline_install")
    url = "file://" + ROOT if p["url"].rstrip("/") in SELF else p["url"]
    work = tempfile.mkdtemp(prefix="catalog-install.")
    try:
        g = ["git", "-c", f"safe.directory={work}", "-C", work]
        for cmd in (["git", "init", "-q", work], [*g, "fetch", "-q", "--depth", "1", url, p["commit"]], [*g, "checkout", "-q", "--detach", "FETCH_HEAD"]):
            r = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
            if r.returncode != 0:
                return [f"{p['name']}: {url} could not be fetched at {p['commit'][:12]}: {((r.stderr or r.stdout).strip().splitlines() or ['git failed'])[-1]}"]
        got = subprocess.run([*g, "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
        if got != p["commit"]:
            return [f"{p['name']}: {url} answered {got[:12]} where the entry pins {p['commit'][:12]}"]
        return offline.run(os.path.join(work, str(p.get("path") or "").strip("/")), "required")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def had_at(ref):
    """existed(folder) for whose: whether this repository had `folder` at
    `ref`, a file or a tree by that name."""
    def existed(folder):
        r = subprocess.run(["git", "-C", ROOT, "cat-file", "-e", f"{ref}:{folder.strip('/')}"], capture_output=True, check=False)
        return r.returncode == 0
    return existed


def files_since(ref):
    """(files, added): what differs from `ref` in this repository's tracked
    files, the working tree's own changes with it, and which of them `ref`
    did not have."""
    r = subprocess.run(["git", "-C", ROOT, "diff", "--name-status", "--no-renames", ref], capture_output=True, text=True, check=False)
    rows = [ln.split("\t", 1) for ln in r.stdout.splitlines() if "\t" in ln] if r.returncode == 0 else []
    return [f for _, f in rows], [f for st, f in rows if st == "A"]


def vendor_of(url):
    """The verified vendor whose repositories this address is among, or ""."""
    try:
        with open(os.path.join(ROOT, "verified-vendors.json"), encoding="utf-8") as f:
            vendors = json.load(f).get("vendors") or []
    except (OSError, ValueError, AttributeError):
        return ""
    for v in vendors:
        for under in v.get("repositories") or [] if isinstance(v, dict) else []:
            # A whole address down to a slash, so one vendor's name is
            # never the start of another's.
            if isinstance(under, str) and under.startswith("https://") and under.endswith("/") and (url.rstrip("/") + "/").startswith(under):
                return str(v.get("name") or under)
    return ""


def away(before, now, reads, pin_for):
    """What a release that reads pack format `reads` could take of the
    index `before` and can no longer take of `now`: a sentence each, []
    when nothing was taken away. An entry it could take (pin_for answered a
    pin, the entry not withdrawn) still answers a pin, or is marked
    withdrawn. `pin_for` is that AerieOS's packformat.pin_for."""
    said = []
    have = {p.get("name"): p for p in now.get("packs", []) if isinstance(p, dict)}
    for was in before.get("packs", []) if isinstance(before, dict) else []:
        if not isinstance(was, dict) or was.get("withdrawn") is True:
            continue
        took = pin_for(was, reads)
        if took is None:
            continue
        name, p = was.get("name"), have.get(was.get("name"))
        if p is None:
            said.append(f"{name} is gone from the index, and it could take it: an entry found wanting is withdrawn (withdrawn: true), "
                        "never taken away from a release that is still listed")
        elif p.get("withdrawn") is not True and pin_for(p, reads) is None:
            said.append(f"{name} has no pin left that it reads (pack format {p.get('format', 1)} now, and it reads up to {reads}; it took the "
                        f"pack format {took.get('format', 1)} pin at {str(took.get('commit'))[:12]}): an entry that moves to a newer format keeps "
                        "its older pin (older) until no listed release needs it")
    return said


def folder_of(p, url, aerieos):
    """(held, doc, why): what the folder an entry pins says of itself, read
    as an install reads it. `held` is (word, sentence) by AerieOS's own
    reading of its manifest (packformat.held, an app's by its images); `doc`
    the manifest as it is written (a pack's bbtool.json, an app's
    bbapp.json); `why` what is wrong where it could not be read, which the
    entry's own comparison (catalogentry.differs) says too."""
    toolpacks, pf = aerieos.toolpacks, aerieos.packformat
    path = str(p.get("path") or "")
    if p.get("kind") == "app":
        got = toolpacks.fetch_folder(url, p["commit"], p["sha256"], path, ("bbapp.json", "compose.yml"))
        if got.get("error"):
            return None, None, got["error"]
        try:
            doc = json.loads(got["files"]["bbapp.json"].decode("utf-8"))
            compose = got["files"]["compose.yml"].decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, None, "its bbapp.json is not JSON"
        seen = aerieos.nasapps.held_of({"compose": compose})
        return (seen["word"], seen["why"]), doc if isinstance(doc, dict) else {}, ""
    if p.get("tier") == "official":
        # One of AerieOS's own: its manifest alone, as large as a shipped
        # row's recipe is, validated on the entry's word that it is one.
        got = toolpacks.fetch_folder(url, p["commit"], p["sha256"], path, (toolpacks.MANIFEST,))
        if got.get("error"):
            return None, None, got["error"]
        try:
            doc = json.loads(got["files"][toolpacks.MANIFEST].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, None, f"its {toolpacks.MANIFEST} is not JSON"
        m, errors = toolpacks.validate(doc, (), official=True)
        if errors:
            return None, None, f"{toolpacks.MANIFEST} needs fixing: " + "; ".join(errors)
        return pf.held(m), doc, ""
    got = toolpacks.fetch(url, p["commit"], (), p["sha256"], path)
    if got.get("error"):
        return None, None, got["error"]
    return (got["held"]["word"], got["held"]["why"]), got["manifest"], ""


def check_entry(p, aerieos):
    """What is wrong with one entry at the pin a release takes, fetched at
    that pin: a list, empty when an install would take it. `p` is the entry
    as that AerieOS takes it (packformat.pin_for); `aerieos` its modules:
    toolpacks, nasapps, packformat and catalogentry."""
    pf = aerieos.packformat
    name, path = p["name"], str(p.get("path") or "")
    url = p["url"]
    # This repository's own entries are read from the checkout CI made,
    # with its whole history, rather than fetched back from GitHub.
    if url.rstrip("/") in SELF:
        url = "file://" + ROOT
    # Who the tool is by, on every entry: its card names them beside the
    # tier, which says only who packaged it.
    maker = p.get("maker")
    if not (isinstance(maker, str) and maker.strip() and len(maker) <= 60 and maker.isprintable() and maker == " ".join(maker.split())):
        return [f"{name}: an entry names who its tool is by, an organization or a person, in maker (one line of up to 60 characters)"]
    # What it is about and when it came: one to three of the topics the
    # AerieOS checked against keeps, and the day it was added.
    why = pf.topics_refused(p)
    if why:
        return [f"{name}: {why}"]
    if p.get("added") is not None and not re.fullmatch(r"20\d\d-[01]\d-[0-3]\d", str(p.get("added"))):
        return [f"{name}: added is the day the entry came into the catalog, as YYYY-MM-DD"]
    if p["tier"] == "official" and not (p["url"].rstrip("/") in SELF and path.startswith(OWN)):
        return [f"{name}: an official entry is one of this repository's own, in its packs/official, packs/agents or packs/services"]
    # Packaged by Aerie is this repository's own too: what its maintainers
    # wrote is kept here, never pointed at somewhere else.
    if p["tier"] == "aerie" and not (p["url"].rstrip("/") in SELF and path.startswith("packs/")):
        return [f"{name}: an aerie entry (Packaged by Aerie) is a pack this repository holds, under its packs/"]
    # Verified is a vendor's own pack, from a vendor verified-vendors.json
    # lists with the addresses its repositories are under.
    if p["tier"] == "verified":
        who = vendor_of(p["url"])
        if not who:
            return [f"{name}: a verified entry is in a repository of a vendor verified-vendors.json lists; {p['url']} is under none of them"]
    # Everything the entry repeats of its manifest, by the reader an
    # install uses: the folder fetched at the pin and held to its sha256,
    # its manifest validated, and each thing the pin says compared.
    bad = [f"{name}: {s}" for s in aerieos.catalogentry.differs(p, url)]
    held, doc, why = folder_of(p, url, aerieos)
    if why:
        return bad or [f"{name}: {why}"]
    # No entry is open: what it fetches is held to something it carries.
    word, sentence = held
    if word not in ("pinned", "installer"):
        bad.append(f"{name} reads {word}: {sentence}. The catalog holds no open entry: whatever an entry fetches from somewhere else is held to "
                   "something the entry carries (pinned), or its pinned installer says in a sentence what it downloads by itself (installer)")
    elif p.get("held") is None:
        bad.append(f"{name}: its entry says no held word, and its manifest reads {word}: AerieOS's tools/packs-export.py --catalog DIR "
                   "--entry FOLDER writes the entry from the folder")
    if p.get("kind") == "app":
        # What an app's manifest says beside what its entry repeats.
        try:
            if not 1 <= int(doc.get("port")) <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            bad.append(f"{name}: bbapp.json names no port")
        if not doc.get("license"):
            bad.append(f"{name}: bbapp.json names no license")
    elif (doc.get("tier") == "official") != (p["tier"] == "official"):
        bad.append(f"{name}: the entry is {p['tier']} and its manifest {doc.get('tier') or 'url'}")
    return bad


class Aerieos:
    """A checkout of AerieOS as the check reads entries with it: the modules
    an install reads the catalog with, and the newest pack format it reads."""

    def __init__(self, checkout):
        dash = os.path.join(checkout, "scripts", "dashboard")
        if not os.path.isfile(os.path.join(dash, "toolpacks.py")):
            sys.exit(f"{checkout} is not a checkout of AerieOS (no scripts/dashboard/toolpacks.py)")
        # The catalog serves the releases from the first that holds every
        # download to its entry: one from before it has no reader for what
        # an entry now says, and nothing here stands in for it.
        if not os.path.isfile(os.path.join(dash, "catalogentry.py")):
            sys.exit(f"{checkout} is an AerieOS from before an entry said what its downloads are held to (no scripts/dashboard/catalogentry.py): "
                     "the catalog serves the releases from the first that reads it, and no earlier one is listed")
        sys.path.insert(0, dash)
        os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
        import catalogentry  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        import nasapps  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        import packformat  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        import toolpacks  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        self.catalogentry, self.nasapps, self.packformat, self.toolpacks = catalogentry, nasapps, packformat, toolpacks
        self.reads = int(packformat.FORMAT)


def pins_read(p, aerieos):
    """Every pin of an entry that this AerieOS reads, as it would take each:
    the one it takes first (its newest readable), then each older pin in a
    format it reads, so a pin is checked by every release that reads it."""
    pf = aerieos.packformat
    formats = [pf.of(p) or 1, *(o["format"] for o in p.get("older") or [])]
    return [pf.pin_for(p, f) for f in formats if f <= aerieos.reads]


def one(checkout, changed_from, since, report):
    """Every entry held to one checkout of AerieOS: lines said as they go,
    and what was read, what was passed over and what was taken away written
    to `report`. `changed_from` names the index whose changed entries alone
    are fetched; `since` the one nothing is to be taken away from."""
    aerieos = Aerieos(checkout)
    pf, reads = aerieos.packformat, aerieos.reads
    with open(INDEX, encoding="utf-8") as f:
        d = json.load(f)
    packs = [p for p in d["packs"] if not p.get("withdrawn")]
    if changed_from:
        packs = changed(packs, changed_from)
    bad, read, past, newest = [], [], [], []
    for p in packs:
        why = pf.older_refused(p)
        if why:
            print(f"FAIL  {p['name']}: {why}")
            bad.append(f"{p['name']}: {why}")
            continue
        pins = pins_read(p, aerieos)
        if not pins:
            print(f"past  {p['name']} has no pin in a pack format this AerieOS reads (up to {reads}): it lists nothing of it")
            past.append(p["name"])
            continue
        for n, pin in enumerate(pins):
            said = check_entry(pin, aerieos)
            what = f"{p['name']} at {pin['commit'][:12]}" + ("" if not n and pf.of(pin) == pf.of(p) else f" (its pack format {pf.of(pin)} pin)")
            print(("FAIL  " + "; ".join(said)) if said else f"ok    {what}, {pin.get('held')}")
            bad += said
        read.append(p["name"])
        # Its newest pin is among them where this AerieOS reads that format.
        if (pf.of(p) or 1) <= reads:
            newest.append(p["name"])
    # Nothing is taken away from this release: what it could take at the
    # index it is compared with, it can still take.
    gone = away(index_at(since), d, reads, pf.pin_for) if since else []
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"reads": reads, "read": read, "newest": newest, "past": past, "bad": bad, "away": gone}, f)
    return 1 if bad or gone else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--builderbot", action="append", default=[], metavar="[NAME=]DIR",
                    help="a checkout of AerieOS; name one for each release still supported (none, with --whose-from: whose alone)")
    ap.add_argument("--changed-from", default="", metavar="REF")
    ap.add_argument("--whose-from", default="", metavar="REF",
                    help="say whose each entry is that differs from the index at REF, and refuse a change that crosses owners")
    ap.add_argument("--outside", nargs="?", const="", default=None, metavar="OWNER",
                    help="with --whose-from or --changed-from: the change comes from outside this repository, a pull request from OWNER's fork")
    ap.add_argument("--every-pin", action="store_true",
                    help="with --whose-from or --changed-from: hold every entry's pin to a branch or a tag of its repository, not only the ones that moved")
    ap.add_argument("--run-installs", action="store_true",
                    help="with --whose-from or --changed-from: install each third party's pack that differs, with no network beyond what it declares")
    ap.add_argument("--signed", action="store_true")
    ap.add_argument("--one", default="", help=argparse.SUPPRESS)
    ap.add_argument("--since", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    releases = listed()
    if not a.builderbot and not a.whose_from:
        if not releases:
            # Nothing to hold an entry to: said, and a failure, never a pass.
            sys.exit(NO_RELEASE)
        ap.error("name a checkout of AerieOS with --builderbot, or --whose-from REF for whose each changed entry is alone")
    if a.one:
        return one(a.builderbot[0], a.changed_from, a.since, a.one)
    if a.changed_from:
        a.changed_from = fork_of(a.changed_from)
    if a.whose_from:
        a.whose_from = fork_of(a.whose_from)
    signer = _load(os.path.join(HERE, "catalog-sign.py"), "catalog_sign")
    with open(INDEX, encoding="utf-8") as f:
        d = json.load(f)
    # Which AerieOS first reads a pack format is a release's version, and
    # until one is listed there is none to write: said then, and held as
    # soon as a release is listed and wherever the index is a signed one.
    dated = bool(releases) or a.signed
    bad = signer.check_index(d, dated=dated)
    if bad:
        sys.exit("index.json: " + "; ".join(bad))
    problems = 0
    if not releases:
        print("note  no AerieOS release is listed yet (aerieos-releases): tools/aerieos-release.py TAG lists the first once it is out")
        for fmt in signer.undated(d):
            print(f"note  the index's formats does not say which AerieOS first reads pack format {fmt}: tools/aerieos-release.py TAG writes it")
        if a.signed:
            print("FAIL  a signed index is held to the releases it serves, and none is listed")
            problems += 1
    packs = [p for p in d["packs"] if not p.get("withdrawn")]
    if a.changed_from:
        packs = changed(packs, a.changed_from)
    if not a.builderbot:
        packs = []
    # Each checkout in a process of its own: two releases' modules of one
    # name cannot be loaded side by side.
    import tempfile
    read_by, newest_by = {p["name"]: [] for p in packs}, set()
    for spec in a.builderbot:
        label, _, where = spec.rpartition("=")
        label = label or os.path.basename(os.path.normpath(where))
        with tempfile.NamedTemporaryFile("r", suffix=".json") as rep:
            print(f"== AerieOS {label}", flush=True)
            # What a change started from, for what it may not take away:
            # the index --changed-from or --whose-from names.
            since = a.whose_from or a.changed_from
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--builderbot", where, "--one", rep.name,
                                *(["--changed-from", a.changed_from] if a.changed_from else []), *(["--since", since] if since else [])], check=False)
            try:
                got = json.load(rep)
            except ValueError:
                sys.exit(f"the check against AerieOS {label} did not finish (exit {r.returncode})")
        problems += len(got["bad"]) + len(got["away"])
        for name in got["read"]:
            read_by.setdefault(name, []).append(label)
        newest_by.update(got["newest"])
        for ln in got["away"]:
            print(f"FAIL  taken away from AerieOS {label}: {ln}")
        print(f"   AerieOS {label} reads pack format {got['reads']}: {len(got['read'])} read, {len(got['past'])} past it, "
              f"{len(got['bad']) + len(got['away'])} problem(s)")
    # One no release named here reads cannot be installed by anybody, and a
    # newest pin none of them reads was checked by nobody: neither is signed.
    for p in packs:
        if not read_by.get(p["name"]):
            print(f"FAIL  {p['name']} is pack format {p.get('format', 1)}, which no AerieOS named here reads: name the release that does")
            problems += 1
        elif p["name"] not in newest_by:
            print(f"FAIL  {p['name']}'s newest pin is pack format {p.get('format', 1)}, which no AerieOS named here reads, so nothing here "
                  f"checked it (its older pin was read by {', '.join(read_by[p['name']])}): name the release that reads it")
            problems += 1
    # Whose each changed entry is, and a change that crosses owners refused.
    since = a.whose_from or a.changed_from
    if since:
        files, added = files_since(since)
        said, crossed = whose(index_at(since), d, files, a.outside is not None, added, a.outside or "", had_at(since))
        print(f"== whose, against {since}", flush=True)
        for ln in said or ["whose: no entry differs"]:
            print("   " + ln)
        for ln in crossed:
            print("FAIL  " + ln)
        problems += len(crossed)
    # A pin is on a branch or a tag of the repository its entry names: the
    # ones that moved, or every one where nothing says what a change started
    # from and wherever the run asks for all of them.
    pins = pins_to_hold(index_at(since) if since else {}, d, every=a.every_pin or not since)
    print(f"== {len(pins)} pin(s) held to a branch or a tag of the repository named" + (f": the ones that moved since {since}" if since and not a.every_pin else ""),
          flush=True)
    for ln in unreachable(pins):
        print("FAIL  " + ln)
        problems += 1
    if since:
        # A third party's pack that differs is installed here with no
        # network beyond the downloads it declares: one that fetches
        # anything else fails before a maintainer reads it.
        if a.run_installs:
            before = {p.get("name"): p for p in index_at(since).get("packs", []) if isinstance(p, dict)}
            for p in d["packs"]:
                if p.get("withdrawn") or not owner_of(p) or before.get(p.get("name")) == p or p.get("kind") in ("app", "service"):
                    continue
                print(f"== {p['name']} installed with no network beyond what it declares", flush=True)
                said = installs_offline(p)
                for ln in said:
                    print("FAIL  " + ln)
                problems += len(said)
    if a.signed:
        signer.verify(os.path.join(ROOT, "catalog.pub"))
    if not a.builderbot:
        print(f"whose alone, no entry read: {problems} problem(s)")
        return 1 if problems else 0
    print(f"{len(packs)} entr{'y' if len(packs) == 1 else 'ies'} held to {len(a.builderbot)} AerieOS release(s), {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
