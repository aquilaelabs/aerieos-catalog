#!/usr/bin/env python3
"""The catalog's index, signed by its maintainers (R169 step 2).

    tools/catalog-sign.py keygen KEYFILE         a new Ed25519 pair: the private half to KEYFILE (0600), the public half printed
    tools/catalog-sign.py sign KEYFILE           index.json signed into index.sig
    tools/catalog-sign.py verify PUBFILE         index.sig checked against index.json with the public half

The index is index.json: {"version": 1, "generated": "...", "packs": [{name, url,
commit, sha256, tier, withdrawn, about, platforms}]}, each pack pinned to an exact
commit and the sha256 of its archive at that commit, never latest. The signature
is Ed25519 over the index's bytes; the public half ships with BuilderBot, so an
index that was tampered with on the way is refused there. A pull request adds or
changes an entry; a maintainer signs the index when it is merged.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
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
        if p.get("tier") not in ("vetted", "official"):
            bad.append(f"{where}.tier is vetted or official")
        if not isinstance(p.get("withdrawn", False), bool):
            bad.append(f"{where}.withdrawn is true or false")
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


def sign(keyfile):
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
    elif len(argv) == 2 and argv[0] == "verify":
        verify(argv[1])
    elif argv == ["stamp"]:
        with open(INDEX, encoding="utf-8") as f:
            d = json.load(f)
        d["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(INDEX, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True); f.write("\n")
        print("stamped")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
