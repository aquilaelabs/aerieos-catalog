#!/usr/bin/env python3
"""The vetting check (R169 step 3): what CI runs on every pull request and
every push, before a maintainer reviews an entry and signs the index.

    tools/catalog-check.py --builderbot DIR [--changed-from REF] [--signed]

DIR is a checkout of BuilderBot, whose own fetch and validators are the ones
used, so an entry passes here exactly when an install would take it. Each
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
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
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


def _key(p):
    return tuple(str(p.get(k) or "") for k in ("url", "commit", "sha256", "path", "kind"))


def changed(packs, ref):
    """The entries that differ from the index at `ref`, by what they pin."""
    r = subprocess.run(["git", "-C", ROOT, "show", f"{ref}:index.json"], capture_output=True, text=True, check=False)
    try:
        before = {p.get("name"): _key(p) for p in json.loads(r.stdout).get("packs", [])} if r.returncode == 0 else {}
    except ValueError:
        before = {}
    return [p for p in packs if before.get(p.get("name")) != _key(p)]


def check_entry(p, toolpacks, nasapps):
    """What is wrong with one entry, fetched at its pin: a list, empty when
    an install would take it."""
    name, path = p["name"], str(p.get("path") or "")
    url = p["url"]
    # This repository's own entries are read from the checkout CI made,
    # with its whole history, rather than fetched back from GitHub.
    if url.rstrip("/") in SELF:
        url = "file://" + ROOT
    if p["tier"] == "official" and not (p["url"].rstrip("/") in SELF and path.startswith(OWN)):
        return [f"{name}: an official entry is one of this repository's own, in its packs/official, packs/agents or packs/services"]
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
    return bad


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--builderbot", required=True, help="a checkout of BuilderBot")
    ap.add_argument("--changed-from", default="", metavar="REF")
    ap.add_argument("--signed", action="store_true")
    a = ap.parse_args(argv)
    dash = os.path.join(a.builderbot, "scripts", "dashboard")
    if not os.path.isfile(os.path.join(dash, "toolpacks.py")):
        sys.exit(f"{a.builderbot} is not a checkout of BuilderBot (no scripts/dashboard/toolpacks.py)")
    sys.path.insert(0, dash)
    os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
    import nasapps  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    import toolpacks  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    signer = _load(os.path.join(HERE, "catalog-sign.py"), "catalog_sign")
    with open(INDEX, encoding="utf-8") as f:
        d = json.load(f)
    bad = signer.check_index(d)
    if bad:
        sys.exit("index.json: " + "; ".join(bad))
    packs = [p for p in d["packs"] if not p.get("withdrawn")]
    if a.changed_from:
        packs = changed(packs, a.changed_from)
    for p in packs:
        said = check_entry(p, toolpacks, nasapps)
        print(("FAIL  " + "; ".join(said)) if said else f"ok    {p['name']} at {p['commit'][:12]}")
        bad += said
    if a.signed:
        signer.verify(os.path.join(ROOT, "catalog.pub"))
    print(f"{len(packs)} entr{'y' if len(packs) == 1 else 'ies'} fetched, {len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
