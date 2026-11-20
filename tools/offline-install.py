#!/usr/bin/env python3
"""A pack's install run with no network beyond the downloads it declares.

    tools/offline-install.py DIR [--cut required|auto]

DIR holds a pack's files at the commit an entry pins, its bbtool.json among
them. What an install on a node does is done here in a scratch copy: each
download the manifest declares for this machine (install.fetch: an https
address, the file inside the pack it is kept as, and what holds it) is
fetched and held, and then the install steps and the verify command run
with the network cut. A step that reaches for anything the manifest did not
declare fails, here, before a maintainer reads the pack and long before a
node installs it.

A download is held as an install holds it: to its sha256, or, from pack
format 5, to its publisher's detached signature (signed: {sig, keys}) under
the armored key the manifest carries by that name (install.keyring), checked
with gpgv against that key and no other. One that names a platform is
fetched on that platform alone, and {version} in an address is filled with
the version the download says it is. A pack that says its installer keeps
the network (install.online, a sentence) has what it declares fetched and
held all the same, and its steps then run with the network, said here in its
own sentence: that is the one way a step keeps it.

The network is cut with a network namespace of the step's own: as the same
account where this machine lets an account make one, else through sudo (a
hosted runner's way). --cut required, which is what the catalog's check
passes, fails when the machine can do neither; --cut auto says so and runs
nothing, since steps run with the network would prove nothing.

A pack that names no linux platform this machine is, is not run: said, and
no failure. The system packages it names for apt are installed first, with
the network, where apt-get and sudo are there.

Exit 0 when the install went through or was not for this machine, 1 with
each problem in a sentence otherwise.
"""
import argparse
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

STEP_TIMEOUT = 900
FETCH_MAX_BYTES = 4 << 30
REL = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9._/-]{1,200}$")
PKG = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,100}$")


def say(line):
    print(line, flush=True)


def here():
    """This machine as a manifest names one: linux/amd64."""
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    return f"{platform.system().lower()}/{arch}"


def for_here(platforms):
    me = here()
    return any(p == me or p == me.split("/")[0] + "/*" for p in platforms or [])


def musl():
    """Whether this machine's C library is musl (Alpine): it cannot load a
    glibc build, so a download may be named for linux-musl/<arch>."""
    return bool(glob.glob("/lib/ld-musl-*.so.1"))


def fetched_here(plat):
    """Whether a declared download named for `plat` is one this machine
    fetches, as an install decides it: one that names none is every
    machine's; "<os>/<arch>" and "<os>/*" are this system's; and
    linux-musl/<arch> is a musl machine's alone."""
    if not plat:
        return True
    system, _, arch = str(plat).partition("/")
    mine, _, my_arch = here().partition("/")
    if system == "linux-musl":
        return mine == "linux" and musl() and arch in (my_arch, "*")
    return system == mine and arch in (my_arch, "*")


def cut_words():
    """The words that run a command with no network on this machine, or []."""
    uid, gid = os.getuid(), os.getgid()
    for words in (["unshare", "--user", f"--map-user={uid}", f"--map-group={gid}", "--net"],
                  ["env", "TAR_OPTIONS=--no-same-owner", "unshare", "--user", "--map-root-user", "--net"],
                  ["sudo", "-n", "unshare", "--net", "--", "sudo", "-n", "-u", f"#{uid}", "--"]):
        try:
            if subprocess.run([*words, "true"], capture_output=True, timeout=30, check=False).returncode == 0:
                return words
        except (OSError, subprocess.SubprocessError):
            continue
    return []


def fetch(url, sha256, dest):
    """One declared download into `dest`, held to its sha256 where one is
    named ("" for a file something else holds: a signature, fetched to be
    checked with): "" or what is wrong."""
    local = os.environ.get("OFFLINE_FILE_URLS") == "1" and url.startswith("file:///")
    if not (url.startswith("https://") or local):
        return f"{url} is not an https address"
    h, n = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            if not local and not r.geturl().startswith("https://"):
                return f"{url} sent the download on to {r.geturl()}, which is not https"
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                n += len(chunk)
                if n > FETCH_MAX_BYTES:
                    return f"{url} is larger than {FETCH_MAX_BYTES >> 30} GB"
                h.update(chunk)
                f.write(chunk)
    except (OSError, ValueError) as e:
        return f"{url} could not be fetched: {e}"
    if sha256 and h.hexdigest() != sha256:
        return f"{url} answered a file whose sha256 is {h.hexdigest()}, and the manifest declares {sha256}"
    return ""


def signed_by(path, sig, armored, work):
    """Whether the file at `path` carries the detached signature at `sig`
    under the armored public key `armored`, and no other key: "" or what is
    wrong. The key is made into a keyring of its own for gpgv, never this
    machine's."""
    if not (shutil.which("gpg") and shutil.which("gpgv")):
        return "there is no gpg and gpgv here to check a publisher's signature with"
    ring = os.path.join(work, "keys-" + hashlib.sha256(armored.encode()).hexdigest()[:16] + ".gpg")
    try:
        made = subprocess.run(["gpg", "--batch", "--dearmor"], input=armored.encode(), capture_output=True, timeout=60, check=False)
        if made.returncode != 0 or not made.stdout:
            return "the key the manifest carries is no armored public key gpg reads"
        with open(ring, "wb") as f:
            f.write(made.stdout)
        seen = subprocess.run(["gpgv", "--keyring", ring, sig, path], capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return f"its signature could not be checked: {e}"
    if seen.returncode != 0:
        return "it does not carry its publisher's signature under the key the manifest carries: " + " ".join((seen.stderr or seen.stdout).split())[-200:]
    return ""


def declared(inst, d, work, name):
    """The downloads `inst` (a manifest's install) declares for this
    machine, each fetched into the pack's copy `d` and held: a list of what
    is wrong, [] when every one is as the manifest says."""
    bad = []
    keyring = inst.get("keyring") if isinstance(inst.get("keyring"), dict) else {}
    for i, f in enumerate(inst.get("fetch") or []):
        f = f if isinstance(f, dict) else {}
        url, sha, to, plat, version = (f.get(k) for k in ("url", "sha256", "to", "platform", "version"))
        signed = f.get("signed") if isinstance(f.get("signed"), dict) else None
        ok = isinstance(url, str) and isinstance(to, str) and REL.fullmatch(to) and bool(sha) != bool(signed)
        ok = ok and (not sha or (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)))
        ok = ok and (not signed or (isinstance(signed.get("sig"), str) and isinstance(signed.get("keys"), str)))
        ok = ok and (plat is None or isinstance(plat, str)) and (version is None or isinstance(version, str))
        if not ok:
            bad.append(f"{name}: install.fetch {i + 1} is {{url, sha256, to}}, or with signed ({{sig, keys}}) in the sha256's place")
            continue
        if not fetched_here(plat):
            say(f"left out {to}: it is for {plat}, and this machine is {here()}")
            continue
        # {version} in an address is the version the download says it is.
        url = url.replace("{version}", version) if version else url
        dest = os.path.join(d, to)
        os.makedirs(os.path.dirname(dest) or d, exist_ok=True)
        said = fetch(url, sha or "", dest)
        if not said and signed:
            armored = keyring.get(signed["keys"])
            if not (isinstance(armored, str) and armored.strip()):
                said = f"{to} is signed under {signed['keys']}, which install.keyring does not carry"
            else:
                sig = os.path.join(work, f"sig-{i}")
                said = fetch(signed["sig"].replace("{version}", version) if version else signed["sig"], "", sig) \
                    or signed_by(dest, sig, armored, work)
        if said:
            bad.append(f"{name}: {said}")
        else:
            say(f"fetched  {to} from {url}, " + ("sha256 as declared" if sha else f"signed by its publisher ({signed['keys']})"))
    return bad


def words_of(raw, d):
    return [str(w).replace("{dir}", d) for w in raw] if isinstance(raw, list) and all(isinstance(w, str) for w in raw) else None


def run(src, cut="required"):
    """The problems an offline install of the pack in `src` meets: a list of
    sentences, [] when it went through or is not for this machine."""
    try:
        with open(os.path.join(src, "bbtool.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        return [f"its bbtool.json could not be read: {e}"]
    name = str(m.get("name") or "the pack")
    inst = m.get("install") if isinstance(m.get("install"), dict) else {}
    steps = [words_of(s, "{dir}") for s in inst.get("steps") or []]
    if None in steps:
        return [f"{name}: an install step is a list of words"]
    if not for_here(m.get("platforms")):
        say(f"not run  {name} names {', '.join(m.get('platforms') or []) or 'no platform'}, and this machine is {here()}")
        return []
    if not steps and not inst.get("fetch"):
        say(f"ok       {name} installs by its own files alone: no steps, no downloads")
        return []
    # An installer that keeps the network says so in a sentence, and its
    # steps then run with it: what it declares is held below all the same.
    online = " ".join(inst["online"].split()) if isinstance(inst.get("online"), str) else ""
    words = [] if online else cut_words()
    if not words and not online:
        if cut == "required":
            return [(f"{name}: this machine cannot cut the network for a step (no network namespace as this account or through sudo), "
                     "so its install was not held to what it declares")]
        say(f"not run  {name}: this machine cannot cut the network for a step, and steps run with it would prove nothing")
        return []
    # The system packages it names, with the network, before anything is cut.
    pkgs = [p for p in ((m.get("system") or {}).get("apt") or []) if isinstance(p, str) and PKG.fullmatch(p)]
    if pkgs and shutil.which("apt-get") and subprocess.run(["sudo", "-n", "true"], capture_output=True, check=False).returncode == 0:
        say(f"system   apt-get install {' '.join(pkgs)}")
        subprocess.run(["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", *pkgs], check=False, timeout=STEP_TIMEOUT,
                       stdout=subprocess.DEVNULL)
    work = tempfile.mkdtemp(prefix="offline-install.")
    try:
        d = os.path.join(work, name)
        shutil.copytree(src, d, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        bad = declared(inst, d, work, name)
        if bad:
            return bad
        if online:
            say(f"online   {name} keeps the network for its steps, as its manifest says: {online}")
        # What its steps, its verify and its verbs run by path is marked to
        # run, as an install does: a file committed through a forge's web
        # editor has no executable bit.
        verify = words_of(inst.get("verify"), "{dir}") if inst.get("verify") else None
        progs = [w[0] for w in [*steps, verify or [""], *(v.get("run") or [""] for v in (m.get("verbs") or {}).values() if isinstance(v, dict))]
                 if w and str(w[0]).startswith("{dir}/")]

        def mark():
            for prog in progs:
                full = prog.replace("{dir}", d)
                if os.path.isfile(full):
                    os.chmod(full, os.stat(full).st_mode | 0o755)

        mark()
        home = os.path.join(work, "home")
        os.makedirs(home)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "TMPDIR": work, "LANG": "C.UTF-8", "CI": "true"}
        for what, cmd in [*((f"step {i + 1}", s) for i, s in enumerate(steps)), *([("verify", verify)] if verify else [])]:
            if what == "verify":
                # ...and again once the steps have made what they make, as an install does.
                mark()
            cmd = [w.replace("{dir}", d) for w in cmd]
            say(f"{'online ' if online else 'offline'}  {what}: {' '.join(cmd).replace(d, '{dir}')}")
            try:
                # Its environment said in the words themselves: sudo, where
                # that is how the network is cut, hands on none of its own.
                p = subprocess.run([*words, "env", "-i", *(f"{k}={v}" for k, v in env.items()), *cmd], cwd=d, capture_output=True, text=True,
                                   timeout=STEP_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return [f"{name}: its {what} did not finish within {STEP_TIMEOUT}s" + ("" if online else " with no network")]
            except OSError as e:
                return [f"{name}: its {what} could not be run: {e}"]
            if p.returncode != 0:
                tail = " | ".join((p.stdout + p.stderr).strip().splitlines()[-6:])[:600]
                if online:
                    return [f"{name}: its {what} failed (exit {p.returncode}): {tail or 'it said nothing'}"]
                return [(f"{name}: its {what} failed with no network (exit {p.returncode}): {tail or 'it said nothing'}. "
                         "What an install takes from somewhere else is declared in the manifest, install.fetch (pack format 3), "
                         "each with its address and its sha256")]
        tool = (m.get("layout") or {}).get("tool") if isinstance(m.get("layout"), dict) else None
        if isinstance(tool, str) and REL.fullmatch(tool) and not os.path.exists(os.path.join(d, tool)):
            return [f"{name}: its install went through, and {tool}, which says it is installed, is not there"]
        if online:
            say(f"ok       {name} installs, its steps with the network as its manifest says")
        else:
            say(f"ok       {name} installs with no network beyond the {len(inst.get('fetch') or [])} download(s) it declares")
        return []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir")
    ap.add_argument("--cut", choices=("required", "auto"), default="required")
    a = ap.parse_args(argv)
    bad = run(a.dir, a.cut)
    for b in bad:
        say("FAIL     " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
