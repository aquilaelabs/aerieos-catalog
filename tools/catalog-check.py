#!/usr/bin/env python3
"""The vetting check (R169 step 3): what CI runs on every pull request and
every push, before a maintainer reviews an entry and signs the index.

    tools/catalog-check.py --builderbot [NAME=]DIR ... [--changed-from REF] [--whose-from REF] [--outside] [--signed]

DIR is a checkout of AerieOS, whose own fetch and validators are the ones
used, so an entry passes here exactly when an install would take it. Named
more than once, each is a release still supported (aerieos-releases lists
them), and an entry is held to every one that reads its format: the oldest
install that takes it must take it as the newest does. A release that reads
only an earlier format than an entry's passes it over, as an install of it
lists the card and fetches nothing; an entry no release named here reads is
a failure, since nobody could install it. Each
entry is held to the index's shape (catalog-sign.py's check), then fetched at
the commit it pins: the commit is the one answered, the sha256 of its
archive (of its folder, with a path) is the one the entry names, and its
manifest passes BuilderBot's validator, a tool pack's bbtool.json or an
app's bbapp.json and compose.yml. The entry and its manifest agree on the
name and the platforms, and an official entry is one of BuilderBot's own,
in this repository's packs/official or packs/agents. A withdrawn entry is
held to the shape alone. --changed-from REF fetches only the entries that
differ from the index at REF (a pull request's base); --signed also checks
index.sig against catalog.pub, which is what a push to main must carry.

An entry says the pack format its manifest is written in (`format`, 1 when
it says none), and the two agree: that number is how an install knows,
before it fetches anything, whether the entry is one it reads.

Whose an entry is. An entry at tier official or aerie is this repository's
own; any other is a third party's, its owner the account its repository is
under. --changed-from REF (and --whose-from REF, which fetches nothing less)
says whose each entry is that differs from the index at REF, and refuses a
change that crosses owners: Aerie's own entries and a third party's in one
change, two owners' entries in one change, a third party's entry removed
(one found wanting is withdrawn), handed to another owner, or changed with
no new pin beyond the two things that are the maintainers' to say
(withdrawn and tier), and anything else of this repository changed beside a
third party's entry. --outside says the change comes from outside
this repository (a pull request from a fork): it adds its entry, or moves
its own, and never moves one of Aerie's or changes a file that was here. So work on Aerie's own packs, by a person, a session
or tools/packs-export.py, can never carry a third party's entry along, and
a submission can never reach past its own.
"""
import argparse
import importlib.util
import json
import os
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


def whose(before, after, files=(), outside=False, added=()):
    """(lines, problems): whose each entry is that differs between two
    indexes, and every way the change crosses owners. `files` is what else
    the change touches in this repository, `added` those of them that are
    new; `outside` says the change comes from outside this repository (a
    pull request from a fork), which never moves what was here."""
    was = {p.get("name"): p for p in before.get("packs", []) if isinstance(p, dict)}
    now = {p.get("name"): p for p in after.get("packs", []) if isinstance(p, dict)}
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
        loose = [k for k in fields if k not in MAINTAINERS and k not in LOCKED]
        if loose and not moved:
            bad.append(f"{name}: {', '.join(loose)} changed with no new pin: what a third party's entry says changes only with the commit it pins "
                       "(withdrawn and tier are the maintainers' to change)")
    if outside:
        for name in ours:
            if name in was:
                bad.append(f"{name} is Aerie's own: a change from outside this repository never moves it")
            else:
                bad.append(f"{name} is added at tier {now[name].get('tier')}: a submission is added as vetted, and the maintainers say the rest")
        # ...but its own pack's folder, new or moved with its entry.
        held = sorted(f for f in files if f != "index.json" and not (f in added and f.startswith("packs/"))
                      and not any(f.startswith(d) for d in folders if d != "/"))
        if held:
            bad.append(f"{', '.join(held[:8])}{'...' if len(held) > 8 else ''}: a change from outside this repository adds its entry to index.json, "
                       "and its pack's own new folder under packs/ where it is kept here, and changes nothing that was here (index.sig is the maintainers')")
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


def fork_of(ref):
    """Where this checkout left `ref`: their merge base, so what `ref` has
    gained since is not read as this change's. `ref` itself where git
    names none (a shallow checkout, a ref of another history)."""
    r = subprocess.run(["git", "-C", ROOT, "merge-base", ref, "HEAD"], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ref


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


def _format(doc):
    """The pack format a manifest or an entry says: a whole number from 1,
    1 when it says none, None when what it says is no number."""
    v = doc.get("format", 1) if isinstance(doc, dict) else 1
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None


def check_entry(p, toolpacks, nasapps, reads=1):
    """What is wrong with one entry, fetched at its pin: a list, empty when
    an install would take it. `reads` is the newest pack format this
    checkout reads."""
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
    if p.get("kind") == "app":
        got = toolpacks.fetch_folder(url, p["commit"], p["sha256"], path, ("bbapp.json", "compose.yml"))
        if got.get("error"):
            return [f"{name}: {got['error']}"]
        bad = []
        try:
            meta = json.loads(got["files"]["bbapp.json"].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return [f"{name}: bbapp.json is not JSON"]
        seen = nasapps.check(got["files"]["compose.yml"].decode("utf-8", "replace"))
        if seen.get("error"):
            bad.append(f"{name}: compose.yml: {seen['error']}")
        if meta.get("name") != name:
            bad.append(f"{name}: bbapp.json names itself {meta.get('name')!r}")
        try:
            if not 1 <= int(meta.get("port")) <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            bad.append(f"{name}: bbapp.json names no port")
        if not meta.get("license"):
            bad.append(f"{name}: bbapp.json names no license")
        if _format(meta) != _format(p):
            bad.append(f"{name}: the entry says pack format {p.get('format', 1)} and its bbapp.json {meta.get('format', 1)}")
        # The framework's version and the maker an entry says are its manifest's.
        if (meta.get("framework") or "") != (p.get("framework") or ""):
            bad.append(f"{name}: the entry says framework {p.get('framework') or '(none)'} and its bbapp.json {meta.get('framework') or '(none)'}")
        if meta.get("maker") != p.get("maker"):
            bad.append(f"{name}: the entry says it is by {p.get('maker')!r} and its bbapp.json {meta.get('maker')!r}")
        return bad
    got = toolpacks.fetch(url, p["commit"], (), p["sha256"], path)
    if got.get("error"):
        return [f"{name}: {got['error']}"]
    m, bad = got["manifest"], []
    # A shipped toolchain's name may carry the store's colon (android:cmake),
    # which an index name never does: its entry spells it with a dash.
    if m.get("name") != name and not (p["tier"] == "official" and str(m.get("name")).replace(":", "-") == name):
        bad.append(f"{name}: its manifest names it {m.get('name')!r}")
    if sorted(m.get("platforms") or []) != sorted(p.get("platforms") or []):
        bad.append(f"{name}: the entry's platforms {p.get('platforms')} are not its manifest's {m.get('platforms')}")
    if (m.get("tier") == "official") != (p["tier"] == "official"):
        bad.append(f"{name}: the entry is {p['tier']} and its manifest {m.get('tier') or 'url'}")
    # The format the manifest says is the entry's: a checkout that knows
    # the number keeps it on what it validated.
    # Its label, where the entry says one, is its manifest's.
    if p.get("label") and m.get("label") and p["label"].strip() != m["label"]:
        bad.append(f"{name}: the entry calls it {p['label']!r} and its manifest {m['label']!r}")
    if "format" in m and m["format"] != _format(p):
        bad.append(f"{name}: the entry says pack format {p.get('format', 1)} and its manifest {m['format']}")
    # ...and so are the framework's version it is written for and who its
    # tool is by, where the checkout reads them (one from before the
    # framework's second number keeps neither, and is not asked).
    if "framework" in m and m["framework"] != (p.get("framework") or f"{_format(p)}.0"):
        bad.append(f"{name}: the entry says framework {p.get('framework') or str(_format(p)) + '.0'} and its manifest {m['framework']}")
    if m.get("maker") and m["maker"] != p.get("maker"):
        bad.append(f"{name}: the entry says it is by {p.get('maker')!r} and its manifest {m['maker']!r}")
    # The AerieOS release lines it works with are the entry's too: an
    # install on another line reads the entry alone, and leaves its card out.
    if sorted(m.get("works_with") or []) != sorted(p.get("works_with") or []):
        bad.append(f"{name}: the entry says it works with {p.get('works_with') or 'every AerieOS'} and its manifest {m.get('works_with') or 'every AerieOS'}")
    return bad


def one(checkout, changed_from, report):
    """Every entry held to one checkout of AerieOS: lines said as they go,
    and what was read and what was passed over written to `report`."""
    dash = os.path.join(checkout, "scripts", "dashboard")
    if not os.path.isfile(os.path.join(dash, "toolpacks.py")):
        sys.exit(f"{checkout} is not a checkout of AerieOS (no scripts/dashboard/toolpacks.py)")
    sys.path.insert(0, dash)
    os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
    import nasapps  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    import toolpacks  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    # The newest format it reads: its packformat's, 1 for a release from
    # before the number.
    try:
        import packformat  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        reads = int(packformat.FORMAT)
    except ImportError:
        reads = 1
    with open(INDEX, encoding="utf-8") as f:
        d = json.load(f)
    packs = [p for p in d["packs"] if not p.get("withdrawn")]
    if changed_from:
        packs = changed(packs, changed_from)
    bad, read, past = [], [], []
    for p in packs:
        fmt = _format(p) or 1
        if fmt > reads:
            print(f"past  {p['name']} is pack format {fmt}: this AerieOS reads up to {reads} and lists its card with what it needs")
            past.append(p["name"])
            continue
        said = check_entry(p, toolpacks, nasapps, reads)
        print(("FAIL  " + "; ".join(said)) if said else f"ok    {p['name']} at {p['commit'][:12]}")
        bad += said
        read.append(p["name"])
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"reads": reads, "read": read, "past": past, "bad": bad}, f)
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--builderbot", action="append", default=[], metavar="[NAME=]DIR",
                    help="a checkout of AerieOS; name one for each release still supported (none, with --whose-from: whose alone)")
    ap.add_argument("--changed-from", default="", metavar="REF")
    ap.add_argument("--whose-from", default="", metavar="REF",
                    help="say whose each entry is that differs from the index at REF, and refuse a change that crosses owners")
    ap.add_argument("--outside", action="store_true",
                    help="with --whose-from or --changed-from: the change comes from outside this repository (a fork's pull request)")
    ap.add_argument("--signed", action="store_true")
    ap.add_argument("--one", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not a.builderbot and not a.whose_from:
        ap.error("name a checkout of AerieOS with --builderbot, or --whose-from REF for whose each changed entry is alone")
    if a.one:
        return one(a.builderbot[0], a.changed_from, a.one)
    if a.changed_from:
        a.changed_from = fork_of(a.changed_from)
    if a.whose_from:
        a.whose_from = fork_of(a.whose_from)
    signer = _load(os.path.join(HERE, "catalog-sign.py"), "catalog_sign")
    with open(INDEX, encoding="utf-8") as f:
        d = json.load(f)
    bad = signer.check_index(d)
    if bad:
        sys.exit("index.json: " + "; ".join(bad))
    packs = [p for p in d["packs"] if not p.get("withdrawn")]
    if a.changed_from:
        packs = changed(packs, a.changed_from)
    if not a.builderbot:
        packs = []
    # Each checkout in a process of its own: two releases' modules of one
    # name cannot be loaded side by side.
    import tempfile
    read_by, problems = {p["name"]: [] for p in packs}, 0
    for spec in a.builderbot:
        label, _, where = spec.rpartition("=")
        label = label or os.path.basename(os.path.normpath(where))
        with tempfile.NamedTemporaryFile("r", suffix=".json") as rep:
            print(f"== AerieOS {label}", flush=True)
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--builderbot", where, "--one", rep.name,
                                *(["--changed-from", a.changed_from] if a.changed_from else [])], check=False)
            try:
                got = json.load(rep)
            except ValueError:
                sys.exit(f"the check against AerieOS {label} did not finish (exit {r.returncode})")
        problems += len(got["bad"])
        for name in got["read"]:
            read_by.setdefault(name, []).append(label)
        print(f"   AerieOS {label} reads pack format {got['reads']}: {len(got['read'])} read, {len(got['past'])} past it, {len(got['bad'])} problem(s)")
    # One no release named here reads cannot be installed by anybody.
    for p in packs:
        if not read_by.get(p["name"]):
            print(f"FAIL  {p['name']} is pack format {p.get('format', 1)}, which no AerieOS named here reads: name the release that does")
            problems += 1
    # Whose each changed entry is, and a change that crosses owners refused.
    since = a.whose_from or a.changed_from
    if since:
        files, added = files_since(since)
        said, crossed = whose(index_at(since), d, files, a.outside, added)
        print(f"== whose, against {since}", flush=True)
        for ln in said or ["whose: no entry differs"]:
            print("   " + ln)
        for ln in crossed:
            print("FAIL  " + ln)
        problems += len(crossed)
    if a.signed:
        signer.verify(os.path.join(ROOT, "catalog.pub"))
    if not a.builderbot:
        print(f"whose alone, nothing fetched: {problems} problem(s)")
        return 1 if problems else 0
    print(f"{len(packs)} entr{'y' if len(packs) == 1 else 'ies'} held to {len(a.builderbot)} AerieOS release(s), {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
