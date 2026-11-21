#!/usr/bin/env python3
"""A pack's install, proved by the installer of an AerieOS release.

    tools/offline-install.py --aerieos CHECKOUT DIR [--cut required|auto]
    tools/offline-install.py --aerieos CHECKOUT --entry FILE [--cut required|auto]

CHECKOUT is a checkout of AerieOS (AERIEOS_CHECKOUT names one too), and the
install is that release's own, from its files, as an install of it would
do it. Nothing of the mechanism is written here a second time:

  the controller's half   scripts/dashboard/toolpacks.py: the pack fetched
                          at its pin and held to the entry's sha256, its
                          manifest validated, the pack kept (add), and the
                          row and the bundle a node is sent written
                          (catalog_json, hosted_files);
  the node's half         scripts/lib/sdk.sh with sdkmeta.py: sdk_install,
                          which fetches the pack at its commit, fetches each
                          download the manifest declares for this machine
                          and holds it to its sha256 or its publisher's
                          signature, cuts the network (sdk_net_cut, with
                          nodes/bb-netcut where the account may make no
                          network namespace itself), and runs the steps and
                          the verify behind the cut;
  the system packages     scripts/agent: which of the manifest's packages
                          this machine lacks (sysdeps_missing) and the
                          words that install them (pkg_backend).

What is left here is the driver: a scratch state directory for the
controller's half (look, keep), a scratch store for the node's, the files
laid out between them as a node's bundle has them, and four things an install has
somebody else do. The system packages are installed by running the agent's
own words through sudo, since the agent's job that runs them is a method of
its worker and not a program. A folder that is not a repository yet (DIR)
is committed to a scratch one, as nothing can be fetched at a commit before
there is one. No step keeps a way to root: see below. And the proof has a
verdict where an install has a receipt: a pack whose manifest reads open is
not run, since the catalog holds none; a machine that cannot cut the
network fails the proof (--cut required) where a node would install and
say so; and the file the manifest says shows it is installed has to be
there.

DIR holds a pack's files, its bbtool.json among them: what a submitter runs
before there is an entry. --entry FILE (- for standard input) is an index
entry as index.json has it: the pin this release takes of it is the one
installed (packformat.pin_for), from the entry's repository, or from this
catalog (CATALOG_ROOT's) for a pack kept here.

No way back to root. A hosted runner's account has sudo without a password,
so a step that kept it could leave the cut it runs in or reach the process
that checks it. The whole install is started with no_new_privs set wherever
the machine can cut the network that way (a network namespace of the
account's own), and always for a pack whose steps keep the network. Where
only root can make the namespace, the release's nodes/bb-netcut makes it
and sets no_new_privs itself before it runs the step as the account, and
nothing of the pack runs outside it.

A pack that names no platform this machine is, or no release line this
AerieOS is on, is not run: said, and no failure.

Exit 0 when the install went through or was not for this machine, 1 with
each problem in a sentence otherwise.

OFFLINE_INSTALL_FILES=DIR is the tests' own: a declared download under
https://files.invalid/, a name no host has, is read from DIR.
"""
import argparse
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CATALOG_ROOT") or os.path.dirname(HERE)
SELF = ("https://github.com/aquilaelabs/aerieos-catalog", "https://github.com/aquilaelabs/builderbot-catalog")
ADDRESS = re.compile(r"https://[A-Za-z0-9._~:/@+-]{3,300}")
INSTALL_TIMEOUT = 3600
SYSTEM_TIMEOUT = 900
PR_SET_NO_NEW_PRIVS = 38
# The tests' stand-in for a host: no real pack names it, .invalid being
# nobody's (OFFLINE_INSTALL_FILES).
STAND_IN = "https://files.invalid/"

# The node's half, in the release's own words: sdk.sh sourced as `aerie`
# sources it, and one function of it called.
SOURCED = 'set -euo pipefail\n. "$BB_LIB/common.sh"\n. "$BB_LIB/sdk.sh"\n'
INSTALL = SOURCED + 'sdk_install "$1"\n'
WHERE = SOURCED + 'sdk_dir "$1"\n'
CUTS = SOURCED + 'd="$(mktemp -d)"\nsdk_net_cut "$1" "$d" > /dev/null 2>&1\nrm -rf "$d"\n[ "${#SDK_CUT[@]}" != 0 ]\n'


def say(line):
    print(line, flush=True)


# The words that start a command with no_new_privs set, for good: nothing it
# runs gains a privilege by running a program, sudo among them. A process of
# this python's that sets it on itself and becomes the command.
STARTER = ("import ctypes, os, sys\n"
           "libc = ctypes.CDLL(None, use_errno=True)\n"
           f"if libc.prctl({PR_SET_NO_NEW_PRIVS}, 1, 0, 0, 0) != 0:\n"
           "    sys.exit('no_new_privs could not be set: ' + os.strerror(ctypes.get_errno()))\n"
           "os.execvp(sys.argv[1], sys.argv[1:])\n")
CONFINED = [sys.executable, "-I", "-c", STARTER]


class Product:
    """A checkout of AerieOS as the proof uses it: the controller's module
    that keeps a pack, the node's installer, and the agent's two functions
    for system packages. One checkout to a process: two releases' modules
    of one name cannot be loaded side by side."""
    loaded = None

    def __init__(self, checkout):
        checkout = os.path.abspath(checkout)
        dash, lib = os.path.join(checkout, "scripts", "dashboard"), os.path.join(checkout, "scripts", "lib")
        for need in (os.path.join(dash, "toolpacks.py"), os.path.join(lib, "sdk.sh"), os.path.join(lib, "sdkmeta.py"), os.path.join(checkout, "nodes", "bb-netcut")):
            if not os.path.isfile(need):
                sys.exit(f"{checkout} is not a checkout of an AerieOS whose installer this drives (no {os.path.relpath(need, checkout)})")
        if Product.loaded not in (None, checkout):
            sys.exit(f"one AerieOS to a process: {Product.loaded} is loaded, and {checkout} was asked for")
        Product.loaded = checkout
        self.checkout, self.scripts, self.lib = checkout, os.path.join(checkout, "scripts"), lib
        self.netcut = os.path.join(checkout, "nodes", "bb-netcut")
        for d in (dash, os.path.join(checkout, "scripts", "agent"), lib):
            if d not in sys.path:
                sys.path.insert(0, d)
        # A pack kept in this catalog, or a folder made a repository here,
        # is read from disk by the controller's half.
        os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
        import packformat  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        import sdkmeta  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        import toolpacks  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        from aerieos_agent import backends  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        from aerieos_agent import toolchains as agent  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        self.packformat, self.sdkmeta, self.toolpacks, self.backends, self.agent = packformat, sdkmeta, toolpacks, backends, agent
        try:
            self.version = Path(checkout, "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            self.version = ""
        # The release line a pack's works_with is held to is this release's.
        toolpacks.running_version = lambda: self.version
        with open(os.path.join(checkout, "config", "toolchains.json"), encoding="utf-8") as f:
            self.shipped = {r["name"] for r in json.load(f)["toolchains"] if isinstance(r, dict) and r.get("name")}

    def env(self, node):
        """What the node's half starts with: a store, a home and a
        temporary directory of this run's own, and nothing of the caller's
        but its PATH."""
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(node, "home"), "BUILDER_HOME": os.path.join(node, "home"),
                "TMPDIR": os.path.join(node, "tmp"), "LANG": "C.UTF-8", "CI": "true",
                "BB_SCRIPTS": self.scripts, "BB_LIB": self.lib, "BB_TOOLCHAINS_JSON": os.path.join(node, "config", "toolchains.json"),
                "SDK_ROOT": os.path.join(node, "store"), "BUILDERBOT_NETCUT_BIN": self.netcut,
                **({"BB_TOOLPACKS_FILE_URLS": "1"} if os.environ.get("OFFLINE_INSTALL_FILES") else {})}

    def sh(self, script, name, node, confined=False, timeout=120):
        """One of the node's words run for the pack `name`: the finished
        process, its output captured."""
        return subprocess.run([*(CONFINED if confined else []), "bash", "-c", script, "bash", name], env=self.env(node), cwd=os.path.join(node, "home"),
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout, check=False)

    def cuts(self, name, node, confined):
        """Whether this machine cuts the network for a step, by the
        release's own sdk_net_cut; `confined` asks it of a process that has
        no_new_privs set already."""
        try:
            return self.sh(CUTS, name, node, confined).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def repository_of(src, work):
    """(url, commit) of a scratch repository holding the files of the
    folder `src`, which is no repository yet: what the controller's half
    fetches a pack from."""
    repo = os.path.join(work, "pack")
    shutil.copytree(src, repo, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    git = ["git", "-c", "user.name=AerieOS catalog", "-c", "user.email=catalog@localhost", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-C", repo]
    for args in (["init", "-q", "-b", "main"], ["add", "-A", "--force", "."], ["commit", "-q", "--allow-empty", "-m", "the pack, as it was handed over"]):
        r = subprocess.run([*git, *args], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise OSError(f"no scratch repository could be made of {src}: {(r.stderr or r.stdout).strip()[-300:]}")
    return "file://" + repo, subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def look(product, url, commit, sha256, path, work):
    """The controller's look at a pack before it is kept: (manifest, held)
    as the release's own toolpacks reads it at the pin, fetched and held to
    the entry's sha256 and validated, or a sentence saying why not. Its
    state is a directory under `work`."""
    tp = product.toolpacks
    state = os.path.join(work, "state")
    os.makedirs(state, exist_ok=True)
    tp.configure(state=state, write_json=lambda p, v: Path(p).write_text(json.dumps(v), encoding="utf-8"))
    got = tp.fetch(url, commit, product.shipped, sha256, path)
    return got["error"] if got.get("error") else (got["manifest"], got["held"])


def keep(product, url, commit, sha256, path, tier, work):
    """The pack kept by the controller's half, and what it hands a node:
    (name, node) with `node` the directory a node's bundle is laid out in,
    or a sentence saying why the pack was not taken."""
    tp = product.toolpacks
    node = os.path.join(work, "node")
    for d in (os.path.join(node, "config", "toolpacks"), os.path.join(node, "store"), os.path.join(node, "home"), os.path.join(node, "tmp")):
        os.makedirs(d, exist_ok=True)
    kept = tp.add(url, commit, "the catalog's check", product.shipped, sha256=sha256, tier=product.packformat.tier_of(tier), path=path, may_root=True)
    if kept.get("error"):
        return kept["error"]
    name = kept["pack"]["name"]
    # A node's bundle: the catalog the release ships, the packs' rows beside
    # it, and the bundle of each pack the controller keeps for its nodes.
    shutil.copy(os.path.join(product.checkout, "config", "toolchains.json"), os.path.join(node, "config", "toolchains.json"))
    rows = tp.catalog_json()
    files = os.environ.get("OFFLINE_INSTALL_FILES")
    if files:
        rows = rows.replace(STAND_IN, "file://" + os.path.abspath(files).rstrip("/") + "/")
    Path(node, "config", "toolpacks.json").write_text(rows, encoding="utf-8")
    for arc, src in tp.hosted_files():
        shutil.copy(src, os.path.join(node, arc))
    return name, node


def system_packages(product, node, name):
    """The system packages the pack names that this machine lacks,
    installed before anything is cut: which, and by what words, are the
    release's agent's to say (sysdeps_missing, pkg_backend), and they are
    run here as its job runs them, through sudo where this is not root.
    "" or what went wrong."""
    cat = product.agent.read_catalog(node)
    fam, query, install = product.backends.pkg_backend()
    missing, other = product.agent.sysdeps_missing(cat, name, fam, query)
    if other:
        say(f"system   {name} names system packages for {other[0]} only, and this machine is not one: {' '.join(other[1])}")
    if not missing:
        return ""
    root = root_words()
    if root is None:
        say(f"system   {name} names system packages this account cannot install here (it is not root and has no sudo): {' '.join(missing)}")
        return ""
    say(f"system   {' '.join([*install, *missing])}")
    try:
        p = subprocess.run([*root, "env", "DEBIAN_FRONTEND=noninteractive", *install, *missing], capture_output=True, text=True,
                           timeout=4 * 3600 if fam == "emerge" else SYSTEM_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return f"{name}: its system packages could not be installed: {e}"
    if p.returncode != 0:
        tail = " | ".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-4:])[:400]
        return f"{name}: its system packages did not install (exit {p.returncode}): {tail or 'the package manager said nothing'}"
    return ""


def root_words():
    """The words that run a command as root here: none for root itself,
    sudo where it asks no password, None where there is no way."""
    if os.geteuid() == 0:
        return []
    try:
        ok = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=30, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return ["sudo", "-n"] if ok else None


def installed(product, name, node, confined):
    """The node's half: sdk_install for the pack `name`, its lines said as
    they come. (exit code, the last lines it said); 124 where it did not
    end in time."""
    proc = subprocess.Popen([*(CONFINED if confined else []), "bash", "-c", INSTALL, "bash", name], env=product.env(node), cwd=os.path.join(node, "home"),
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    late = []

    def end():
        late.append(1)
        with_group(proc.pid, signal.SIGKILL)
    clock = threading.Timer(INSTALL_TIMEOUT, end)
    clock.start()
    tail = []
    try:
        assert proc.stdout
        # Lines end where the installer ends them: a progress bar's is a
        # screenful of returns, and its last state is what is said.
        with io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="\n") as lines:
            for line in lines:
                line = line.rstrip("\r\n").rsplit("\r", 1)[-1].rstrip()
                if line:
                    say("   " + line)
                    tail = [*tail, line][-6:]
        code = proc.wait()
    finally:
        clock.cancel()
        # Whatever a step left running in the install's own session ends with it.
        with_group(proc.pid, signal.SIGKILL)
    return (124 if late else code), tail


def with_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except (OSError, ProcessLookupError):
        pass


def prove(product, url, commit, sha256="", path="", tier="vetted", cut="required"):
    """The problems the install of the pack at `url` and `commit` meets by
    this release's installer: a list of sentences, [] when it went through
    or is not for this machine."""
    work = tempfile.mkdtemp(prefix="offline-install.")
    try:
        looked = look(product, url, commit, sha256, path, work)
        if isinstance(looked, str):
            return [looked]
        m, held = looked
        name = m["name"]
        if not any(product.sdkmeta.on_platform(p) for p in m.get("platforms") or []):
            say(f"not run  {name} names {', '.join(m.get('platforms') or []) or 'no platform'}, and this machine is {product.sdkmeta.this_platform()}")
            return []
        if not product.toolpacks.fits(m):
            say(f"not run  {name} works with AerieOS {', '.join(m.get('works_with') or [])}, and this is {product.version}: an install of it lists nothing of it")
            return []
        # The catalog holds no open entry, and an open pack's steps would
        # run here with the network and with whatever this account may do.
        if held.get("word") not in ("pinned", "installer"):
            return [f"{name} reads {held.get('word')}: {held.get('why')}. The catalog holds no open entry, and its install was not run"]
        kept = keep(product, url, commit, sha256, path, tier, work)
        if isinstance(kept, str):
            return [kept]
        name, node = kept
        online = held["word"] == "installer"
        runs = bool(m.get("steps") or m.get("verify"))
        # No way back to root for anything of the pack. With no_new_privs on
        # the whole install wherever this machine can cut the network that
        # way, and always where the steps keep the network; else the
        # release's bb-netcut makes the cut as root and sets it itself.
        confined = True
        if runs and not online and not product.cuts(name, node, confined=True):
            confined = False
            if not product.cuts(name, node, confined=False):
                if cut == "required":
                    return [(f"{name}: this machine cannot cut the network for a step (no network namespace as this account, and none through "
                             "sudo and the release's bb-netcut), so its install was not held to what it declares")]
                say(f"not run  {name}: this machine cannot cut the network for a step, and steps run with it would prove nothing")
                return []
        said = system_packages(product, node, name)
        if said:
            return [said]
        if online:
            say(f"online   {name} keeps the network for its steps, as its manifest says: {held.get('why')}")
        code, tail = installed(product, name, node, confined)
        if code != 0:
            why = f"did not finish within {INSTALL_TIMEOUT}s" if code == 124 else f"failed (exit {code})"
            # The installer's own last word whole, and a little of what a step said before it.
            at = next((i for i in range(len(tail) - 1, -1, -1) if "ERROR:" in tail[i]), len(tail) - 1)
            last = tail[at][:900] if tail else "it said nothing"
            before = " | ".join(ln[:160] for ln in tail[max(0, at - 3):at])
            return [(f"{name}: its install by AerieOS {product.version or 'at this checkout'} {why}: {before + ' | ' if before else ''}{last}. "
                     "What an install takes from somewhere else is declared in the manifest (install.fetch, each download with its address and "
                     "what holds it), and its steps run with no network unless it says install.online")]
        try:
            d = product.sh(WHERE, name, node).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            d = ""
        try:
            how = Path(d, ".bb-net").read_text(encoding="utf-8").splitlines()[0] if d else ""
        except (OSError, IndexError):
            how = ""
        if runs and how != ("online" if online else "cut"):
            return [f"{name}: its steps ran {'with the network' if how == 'open' else 'with nothing said of the network'}, where its manifest reads {held['word']}: nothing was proved"]
        tool = (m.get("layout") or {}).get("tool")
        if tool and not os.path.exists(os.path.join(d, tool)):
            return [f"{name}: its install went through, and {tool}, which says it is installed, is not there"]
        if online:
            say(f"ok       {name} installs by AerieOS {product.version}'s installer, its steps with the network as its manifest says")
        else:
            say(f"ok       {name} installs by AerieOS {product.version}'s installer with no network beyond the {len(m.get('fetch') or [])} download(s) it declares")
        return []
    except (OSError, subprocess.SubprocessError) as e:
        return [f"the install could not be run: {e}"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run(checkout, src, cut="required"):
    """The problems the install of the pack in the folder `src` meets."""
    product = Product(checkout)
    if not os.path.isfile(os.path.join(src, "bbtool.json")):
        return [f"{src} holds no bbtool.json: a pack's folder is what is installed"]
    work = tempfile.mkdtemp(prefix="offline-pack.")
    try:
        url, commit = repository_of(src, work)
        return prove(product, url, commit, cut=cut)
    except OSError as e:
        return [str(e)]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_entry(checkout, entry, cut="required"):
    """The problems the install of an index entry meets, at the pin this
    release takes of it."""
    product = Product(checkout)
    pin = product.packformat.pin_for(entry) if isinstance(entry, dict) else None
    name = str(entry.get("name") or "the entry") if isinstance(entry, dict) else "the entry"
    if pin is None:
        say(f"past     {name} has no pin in a pack format AerieOS {product.version} reads: an install of it lists nothing of it")
        return []
    url = str(pin.get("url") or "").rstrip("/")
    if url in SELF:
        url = "file://" + ROOT
    elif not ADDRESS.fullmatch(url):
        return [f"{name}: {url or 'no address'} is no https address of a repository"]
    if not re.fullmatch(r"[0-9a-f]{40}", str(pin.get("commit") or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256") or "")):
        return [f"{name}: an entry pins a full commit and its archive's sha256"]
    return prove(product, url, pin["commit"], pin["sha256"], str(pin.get("path") or "").strip("/"), str(pin.get("tier") or ""), cut)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", help="a folder holding a pack's files")
    ap.add_argument("--entry", metavar="FILE", help="an index entry, as JSON (- for standard input), in the folder's place")
    ap.add_argument("--aerieos", metavar="CHECKOUT", default=os.environ.get("AERIEOS_CHECKOUT", ""),
                    help="a checkout of the AerieOS release whose installer is driven (AERIEOS_CHECKOUT)")
    ap.add_argument("--cut", choices=("required", "auto"), default="required")
    a = ap.parse_args(argv)
    if not a.aerieos:
        sys.exit("name a checkout of AerieOS with --aerieos (tools/aerieos-checkouts.sh makes one of each release listed): the install is that release's own")
    if bool(a.dir) == bool(a.entry):
        ap.error("a pack's folder, or --entry with an index entry: one of the two")
    if a.entry:
        try:
            if a.entry == "-":
                entry = json.load(sys.stdin)
            else:
                with open(a.entry, encoding="utf-8") as f:
                    entry = json.load(f)
        except (OSError, ValueError) as e:
            sys.exit(f"the entry could not be read: {e}")
        bad = run_entry(a.aerieos, entry, a.cut)
    else:
        bad = run(a.aerieos, a.dir, a.cut)
    for b in bad:
        say("FAIL     " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
