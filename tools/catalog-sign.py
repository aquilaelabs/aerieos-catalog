#!/usr/bin/env python3
"""The catalog's index, signed by its maintainers (R169 step 2).

    tools/catalog-sign.py keygen KEYFILE         a new Ed25519 pair: the private half to KEYFILE (0600), the public half printed
    tools/catalog-sign.py sign KEYFILE           index.json stamped with the moment (generated) and signed into index.sig
    tools/catalog-sign.py sign KEYFILE --as-is   signed with the date it carries, for an index stamped already
    tools/catalog-sign.py verify PUBFILE         index.sig checked against index.json with the public half

The index is index.json: {"version": 1, "generated": "...", "packs": [{name, url,
commit, sha256, tier, withdrawn, about, platforms}]}, each pack pinned to an exact
commit and the sha256 of its archive at that commit, never latest. The signature
is Ed25519 over the index's bytes; the public half ships with BuilderBot, so an
index that was tampered with on the way is refused there. A pull request adds or
changes an entry; a maintainer signs the index when it is merged.

A signature says who made an index, never that it is the newest, so an
install refuses one made before the one it holds, by `generated`. Signing
therefore stamps `generated` with the moment it signs, never earlier than
the date the index carried: two different signed indexes never carry one
date, and a later signing is always the later index.
"""
import calendar
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# The catalog this signs: the one this file is in, or CATALOG_ROOT's, which
# is how the sign workflow signs a branch's index with the copy of this
# file main has (as catalog-check.py is run), so that a branch cannot change
# the program that is handed the key.
ROOT = os.environ.get("CATALOG_ROOT") or os.path.dirname(HERE)
INDEX, SIG = os.path.join(ROOT, "index.json"), os.path.join(ROOT, "index.sig")


def _ed():
    from cryptography.hazmat.primitives import serialization          # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ed25519       # noqa: PLC0415
    return serialization, ed25519


def keygen(path):
    serialization, ed25519 = _ed()
    priv = ed25519.Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("builderbot-catalog-ed25519-private " + raw.hex() + "\n")
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("builderbot-catalog-ed25519 " + pub.hex())


def _priv(path):
    serialization, ed25519 = _ed()
    with open(path, encoding="utf-8") as f:
        words = f.read().split()
    if len(words) != 2 or words[0] != "builderbot-catalog-ed25519-private":
        sys.exit("not a catalog private key file")
    return ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(words[1]))


def _pubs(path):
    """The public keys a file names: the key the index is signed with, and
    on a second line its spare, whose private half is kept apart from the
    repository's secret so the first can be replaced with no install cut off."""
    serialization, ed25519 = _ed()
    with open(path, encoding="utf-8") as f:
        lines = [ln.split() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not 1 <= len(lines) <= 2 or any(len(w) != 2 or w[0] != "builderbot-catalog-ed25519" for w in lines):
        sys.exit("not a catalog public key file")
    return [ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(w[1])) for w in lines]


def check_index(d):
    """What the index must be, before it is signed: each entry whole."""
    import re
    bad = []
    if not isinstance(d, dict) or d.get("version") != 1 or not isinstance(d.get("packs"), list):
        return ["index.json is {version: 1, generated, packs: [...]}"]
    for i, p in enumerate(d["packs"]):
        where = f"packs[{i}]"
        if not isinstance(p, dict):
            bad.append(f"{where} is an object"); continue
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", str(p.get("name") or "")):
            bad.append(f"{where}.name is 2 to 40 of a-z, 0-9 and -")
        if not re.fullmatch(r"https://[A-Za-z0-9._~:/@+-]{3,300}", str(p.get("url") or "")):
            bad.append(f"{where}.url is an https git address")
        if not re.fullmatch(r"[0-9a-f]{40}", str(p.get("commit") or "")):
            bad.append(f"{where}.commit is the full 40-character hash, never a branch or a tag")
        if not re.fullmatch(r"[0-9a-f]{64}", str(p.get("sha256") or "")):
            bad.append(f"{where}.sha256 is the archive's sha256 at that commit")
        if p.get("tier") not in ("official", "aerie", "verified", "vetted"):
            bad.append(f"{where}.tier is official (a row AerieOS ships), aerie (a pack its maintainers wrote), verified (a verified vendor's own) or vetted")
        if "label" in p and not (isinstance(p["label"], str) and 0 < len(p["label"].strip()) <= 60):
            bad.append(f"{where}.label is the pack's name as a person reads it, at most 60 characters")
        if not isinstance(p.get("withdrawn", False), bool):
            bad.append(f"{where}.withdrawn is true or false")
        ww = p.get("works_with")
        if ww is not None and not (isinstance(ww, list) and 0 < len(ww) <= 12 and all(isinstance(x, str) and re.fullmatch(r"\d{1,3}\.\d{1,3}", x) for x in ww)):
            bad.append(f"{where}.works_with is the AerieOS release lines its manifest says it works with, e.g. [\"0.9\", \"0.10\"], left out when it names none")
        fmt = p.get("format", 1)
        if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt < 1:
            bad.append(f"{where}.format is the pack format its manifest is written in, a whole number from 1")
    # The first AerieOS that reads each format past the first, for a card
    # on an older one to name.
    since = d.get("formats", {})
    if not isinstance(since, dict) or not all(re.fullmatch(r"[0-9]{1,4}", str(k)) and re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", str(v))
                                              for k, v in since.items()):
        bad.append("formats maps a pack format's number to the first AerieOS that reads it, e.g. {\"2\": \"0.9.0\"}")
    else:
        for i, p in enumerate(d["packs"]):
            if isinstance(p, dict) and isinstance(p.get("format"), int) and p["format"] > 1 and str(p["format"]) not in since:
                bad.append(f"packs[{i}] is pack format {p['format']}, and formats does not say which AerieOS first reads it")
    names = [p.get("name") for p in d["packs"] if isinstance(p, dict)]
    if len(names) != len(set(names)):
        bad.append("a name appears twice")
    return bad


STAMP = "%Y-%m-%dT%H:%M:%SZ"


def stamp(now=None):
    """index.json's `generated` moved to this moment, and written: the date
    an install orders two signed indexes by. Never moved back: a clock
    behind the date the index carries leaves it one second after that date.
    Only that value's characters change, so the file stays as whatever wrote
    it laid it out. The stamp written."""
    with open(INDEX, encoding="utf-8") as f:
        text = f.read()
    d = json.loads(text)
    at = int(time.time() if now is None else now)
    try:
        was = calendar.timegm(time.strptime(str(d.get("generated")), STAMP))
    except ValueError:
        was = None
    if was is not None and at <= was:
        at = was + 1
    said = time.strftime(STAMP, time.gmtime(at))
    if isinstance(d.get("generated"), str):
        new, n = re.subn(r'("generated"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(said), text, count=1)
    else:
        new, n = text, 0
    want = {**d, "generated": said}
    if n != 1 or json.loads(new) != want:
        # No such value at the top to move (or the first one found was not
        # the index's own): written whole, in the order it was read.
        new = json.dumps(want, indent=1) + "\n"
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(new)
    return said


def sign(keyfile, as_is=False):
    if not as_is:
        print(f"index.json stamped {stamp()}")
    with open(INDEX, "rb") as f:
        data = f.read()
    bad = check_index(json.loads(data))
    if bad:
        sys.exit("index.json: " + "; ".join(bad))
    sig = _priv(keyfile).sign(data)
    with open(SIG, "w", encoding="utf-8") as f:
        f.write("builderbot-catalog-ed25519-signature " + sig.hex() + "\n")
    print(f"signed index.json ({len(json.loads(data)['packs'])} pack(s)) into index.sig")


def verify(pubfile):
    with open(INDEX, "rb") as f:
        data = f.read()
    with open(SIG, encoding="utf-8") as f:
        words = f.read().split()
    if len(words) != 2 or words[0] != "builderbot-catalog-ed25519-signature":
        sys.exit("index.sig is not a catalog signature")
    for n, key in enumerate(_pubs(pubfile)):
        try:
            key.verify(bytes.fromhex(words[1]), data)
        except Exception:                                              # noqa: BLE001 (any failure is one answer)
            continue
        print("index.json is signed by that key" if n == 0 else "index.json is signed by that file's spare key")
        return
    sys.exit("index.sig does not match index.json under that key: refused")


def main(argv):
    if len(argv) == 2 and argv[0] == "keygen":
        keygen(argv[1])
    elif len(argv) == 2 and argv[0] == "sign":
        sign(argv[1])
    elif len(argv) == 3 and argv[0] == "sign" and argv[2] == "--as-is":
        sign(argv[1], as_is=True)
    elif len(argv) == 2 and argv[0] == "verify":
        verify(argv[1])
    elif argv == ["stamp"]:
        print(f"stamped {stamp()}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
