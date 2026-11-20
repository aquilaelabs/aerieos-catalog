# AerieOS catalog

The vetted catalog of tool packs, coding agents and Docker apps for
AerieOS: a searchable list people install from like an app, vetted by
AerieOS's maintainers. This repository holds the index and its signature;
a pack lives in its own repository (or in a folder here), pinned in the
index to an exact commit and the sha256 of its archive at that commit,
never latest.

**To submit an entry**, a tool pack, a coding agent or a Docker app of
yours, read [Submitting to the catalog](https://github.com/aquilaelabs/aerieos/blob/main/docs/submitting.md)
in AerieOS's docs (every install carries it under Help): it goes from
writing the manifest to a merged entry, with a worked example of each
kind. [Submitting a pack](#submitting-a-pack), below, is its short form.

- `index.json`: the entries. `{version: 1, generated, formats, packs:
  [{name, url, commit, path, sha256, tier, withdrawn, about, platforms,
  format, framework, maker, held, online, topics, added, older}]}`. The
  entry of a folder kept here is never typed: AerieOS's
  `tools/packs-export.py --catalog` writes it from the folder it pins
  ([An entry](#an-entry)).
- `index.sig`: an Ed25519 signature over `index.json`'s bytes by the
  maintainers' key. The public half (`catalog.pub`) ships with AerieOS
  (its `config/catalog.pub`), so an index tampered with on the way is
  refused by every install.
- `tools/catalog-sign.py`: `keygen`, `sign` and `verify`. Signing stamps
  the index's `generated` with the moment first, forward only: a signature
  says who made an index and never that it is the newest, so an install
  refuses one made before the one it holds, and two signed indexes never
  carry one date. The private half is a maintainer's own and is never in
  this repository's files: it is kept in the secret `CATALOG_SIGNING_KEY`
  of this repository's environment `sign`, and the `sign` workflow, run by
  hand from `main` with the branch that holds a changed index named,
  checks every entry, stamps and signs the index and commits `index.json`
  and `index.sig` to that branch. What is handed the key is `main`'s: the
  workflow, the tools it runs and the library it installs
  (`tools/sign-requirements.txt`, each file held to its sha256) are the
  copies `main` has, the branch is read as data, and the job that holds
  the key runs nothing of a third party's. The environment `sign` is
  limited to `main` and needs a maintainer's approval, in the repository's
  settings, so a run started from any other branch is given no key.
  `catalog.pub` may name a spare key on a second line: its private half is
  kept apart from that secret, an install reads an index signed by either,
  and so the first key can be lost or replaced with no install cut off.
- `packs/official/NAME`, `packs/agents/NAME` and `packs/services/NAME`:
  every toolchain, coding agent and service AerieOS ships, as a pack in
  bbtool.json's format, written
  by AerieOS's `tools/packs-export.py --catalog` from its own tables so
  the two cannot drift; each has an entry in the index at tier `official`,
  pinned to this repository's commit with its folder as `path` and the
  sha256 of `git archive --format=tar COMMIT PATH`. An install lists them
  on its Library as the shipped rows they are, and the index says which
  commit of the catalog vetted them. A coding agent's pack also says how
  it is installed (`agent.install`: the vendor's installer, how a version
  is pinned, where the program lands, and a `rev` that moves with each
  change), and its index entry repeats that `rev` as `install_rev`: an
  install uses the recipe pinned here when that is higher than the one its
  release shipped, so a vendor's changed installer is answered by a commit
  and a signature here, with no new release.
- `packs/apps/NAME`: a Docker app, `bbapp.json` (name, label, about, port,
  maker, platforms, license) with its `compose.yml` beside it, every image
  named by its digest ([Images by digest](#images-by-digest)). From pack
  format 4 an app declares its own `fields`, each
  the variable it fills, its label, its kind (a folder, a port, a line of
  text, a secret made for it, a choice, a switch), a default and a line of
  help, which New container draws as the app's panel; `${PUID}`, `${PGID}`,
  `${TZ}` and `${PORT}` stay AerieOS's own, asked for in the same words for
  every app. One on the machine's own network says `"network": "host"`. One
  written before format 4 has `${PORT}`, `${DATA}`, `${MEDIA}`, `${PUID}`,
  `${PGID}` and `${TZ}` as its only blanks. Its index entry carries `"kind":
  "app"`. Aerie's own are tier `aerie`: Jellyfin, Plex, Sonarr, Radarr,
  Prowlarr, Seerr, qBittorrent, Immich, Nextcloud, Home Assistant,
  Syncthing and Paperclip, and `packs/apps/whoami` (traefik/whoami, MIT),
  the one to prove a deploy with.
- `packs/`: community manifests under review too, one folder per
  submission, before an entry pins them in the index.

## An entry

An entry pins one manifest and repeats what a card says of it before
anything is fetched:

```json
{"name": "hexkit", "url": "https://github.com/you/hexkit-pack",
 "commit": "89ab...", "sha256": "5e1f...", "tier": "vetted", "withdrawn": false,
 "about": "Looks inside binaries: dumps, strings, headers.",
 "platforms": ["linux/amd64", "linux/arm64"],
 "format": 5, "framework": "5.2", "maker": "Hexkit Project",
 "held": "pinned", "topics": ["devtools"], "added": "2026-11-20"}
```

| Key | What it is |
|---|---|
| `name`, `about`, `maker`, `kind`, `agent` | The entry's own, from its manifest: what it is, who its tool is by, `"kind": "app"` for a Docker app, `"agent": true` for a pack that brings a coding agent. |
| `url`, `path`, `commit`, `sha256` | Where the pack is kept, its folder there, the full commit, and the sha256 of the archive at that commit. |
| `tier`, `withdrawn`, `topics`, `added` | The maintainers' to say: who stands behind it, whether it was withdrawn, one to three of AerieOS's topics, the day it came. |
| `format`, `framework`, `platforms`, `label`, `works_with` | The pinned manifest's: the pack format it needs, the framework's version, where it runs. |
| `held`, `online` | What its downloads are held to: `pinned`, or `installer` with the manifest's sentence ([below](#what-an-entrys-downloads-are-held-to)). |
| `install_rev`, `shipped_rev` | A shipped recipe's rev, so an install fetches the pack only for a newer one. |
| `older` | The pins it keeps for releases that read only an earlier pack format ([An entry's older pins](#an-entrys-older-pins)). |

Nobody types the entry of a pack kept here. `tools/packs-export.py
--catalog DIR --entry FOLDER`, from a checkout of AerieOS, reads the
folder's own manifest at the commit as an install reads it and writes the
entry; `--index` does it for every shipped pack. A submission kept in a
repository of its own writes its entry as
[Submitting to the catalog](https://github.com/aquilaelabs/aerieos/blob/main/docs/submitting.md)
shows. Either way the check reads the entry back as an install does and
refuses whatever the folder does not say.

## What an entry's downloads are held to

Whatever an entry fetches from somewhere else is held to something the
entry itself carries: the sha256 of the exact file, its publisher's
signature under a key the entry carries, a git commit, or for a container
image its digest. The entry is held in turn by the commit the index pins
and by the index's signature, so nothing rests on what a vendor serves on
the day of an install. One word says where an entry stands:

| `held` | What it means |
|---|---|
| `pinned` | Every download it makes is held that way, and its install steps run with no network. |
| `installer` | The same for everything it declares, and its pinned installer downloads the rest by itself. The entry says what, in one sentence (`online`). |
| `open` | Anything else: a download checked only against its own origin, a tag with no digest, steps that run with the network and say nothing. |

**The catalog holds no `open` entry.** The check works the word out from
the manifest with AerieOS's own reading (`packformat.held`), holds the
entry's `held` to it, and refuses one that reads `open` or says no word,
naming the part that is held to nothing. It is one mechanism for a
toolchain AerieOS ships and for anybody's pack: nothing in the check or
the tools knows a vendor. AerieOS's docs/tool-packs.md,
[Declared downloads](https://github.com/aquilaelabs/aerieos/blob/main/docs/tool-packs.md#declared-downloads),
has every shape a manifest can write.

### Images by digest

A Docker app names every image in its `compose.yml` by the digest of what
is pulled: `name:tag@sha256:` and the digest's 64 hex digits. A node pulls
and runs that manifest whatever the registry serves under the tag later,
and the tag beside it is what a person reads. For an image built for
several platforms the digest is the manifest list's, so one line serves
amd64 and arm64. AerieOS's own services name their images the same way in
their pack's `images`. `tools/pins.py --catalog DIR pin NAME` gives an
image written with its tag alone its digest.

## Who stands behind an entry

Each entry says its `tier`, and an install's Library shows it in a person's
words:

| On the card | `tier` | What it is |
|---|---|---|
| Packaged by Aerie | `official` | One of the toolchains, coding agents and services AerieOS ships, as a pack (`packs/official`, `packs/agents`, `packs/services`). |
| Packaged by Aerie | `aerie` | A pack AerieOS's maintainers wrote, for somebody else's tool or an app; it lives in this repository (`packs/aerie`, `packs/apps`). |
| Verified | `verified` | A vendor's own pack, in a repository of a vendor `verified-vendors.json` lists: a shorter list than vetted, since the maintainers have checked who the vendor is. |
| Vetted | `vetted` | Anybody's pack, reviewed by the maintainers. |

`verified-vendors.json` is `{"vendors": [{"name": "...", "repositories":
["https://github.com/ORG/"]}]}`: an entry is verified only when its
address is under one of a listed vendor's. An AerieOS from before `aerie`
and `verified` reads both as vetted.

The tier says who stands behind the pack, never who made the tool: a pack
Packaged by Aerie is usually for somebody else's program. So every entry
also names who its tool is by in `maker`, an organization or a person
(`"maker": "Google"`), in its manifest and again in its index entry, and a
card shows it to the left of the tier. A pack that puts several makers'
tools together is by whoever put it together (AerieOS, for a shipped
toolchain) and lists each under `credits`, `[{"name", "maker"}]`, in its
manifest, which its Details page reads out. The check refuses an entry
that names no maker.

## Whose an entry is

An entry at tier `official` or `aerie` is this repository's own. Any other
is a third party's: its owner is the account its repository is under, and
nobody else's change moves it. The check (`tools/catalog-check.py`) says
whose each changed entry is, on every pull request, on every push to
`main` and before the index is signed, and refuses a change that crosses
owners:

- Aerie's own entries and a third party's are never moved by one change.
  Work on the shipped packs, by a maintainer, a coding session or
  AerieOS's `tools/packs-export.py` (which rewrites the `official` entries
  alone and keeps every other as it was), cannot carry a third party's
  entry along.
- One change moves one owner's entries.
- A third party's entry changes only with the commit it pins: a new
  `commit` and `sha256`, and what the manifest at that commit says. Its
  `url` and `kind` never change, and it is never handed to another owner:
  a pack that moved is a new entry.
- With no new pin, only `withdrawn` and `tier` change, the two things that
  are the maintainers' to say, and what their tools write from the
  manifest at the pin and the check verifies against it: `held`, `online`,
  `older`, `format` and `framework`. An entry found wanting is withdrawn,
  never removed.
- A change that moves a third party's entry touches `index.json` (and
  `index.sig`, which the maintainers' workflow commits; the pack's own
  folder, where it is kept here) and nothing else of this repository.

- A pull request from a fork comes from outside: it adds its entry (as
  `vetted`) or moves its own, with its pack's own folder under `packs/`
  where the pack is kept here, and never moves one of Aerie's entries or
  changes a file that was here.

A pull request is held to the copy of the check `main` has, so it cannot
loosen the rule it is held to; `.github/CODEOWNERS` names the maintainers
for the signature, the key, the tools, the workflows, the verified vendors
and Aerie's own packs.

## What an install downloads

An entry pins a pack's own files. What the pack's install then takes from
somewhere else is declared in its manifest (`install.fetch`): each
download's `https` address, the file inside the pack it is kept as, and
what holds it, the sha256 of what the address answers or its publisher's
signature under a key the manifest carries. One may be named for a
platform. AerieOS fetches each and holds it, and the install steps then
run with no network, so a pinned commit pins everything the install
brings. A pack whose installer must download the rest by itself says so
in one sentence (`install.online`), which is the one way its steps keep
the network, and reads `installer`.

The check holds a third party's pack to that before a maintainer reads it:
`tools/offline-install.py` takes the pack at its pin, fetches what it
declares, and runs its install steps and its verify command with the
network cut, on the check's own runner. A step that reaches for anything
the manifest did not declare fails there, with what to declare. A pack
whose install needs nothing from outside declares nothing and passes the
same way.

## The framework's version

The framework a manifest is written in has a version of its own, apart
from AerieOS's, and it moves whenever the framework changes: two numbers,
`X.Y`. X is the pack format, which moves when an older AerieOS could not
run an entry at all (it hides the entry and says what it needs). Y moves
when something is added that an older AerieOS simply leaves out. A
manifest says both, `"format": 2` and `"framework": "2.1"`, its index entry
repeats them, and the check holds what a manifest uses to the version it
says. AerieOS's docs/tool-packs.md lists what each version added and what
an AerieOS from before it does with such an entry.

## The format, and what it promises

A manifest is written in AerieOS's pack format, which has a number and only
grows: a manifest valid at one number is valid at every later one, so
nothing here is rewritten because something was added beside it. A manifest
says the number it needs (`format`, 1 when it says none), its entry repeats
it, and the index's `formats` says which AerieOS first reads each number
past the first. AerieOS's `docs/tool-packs.md` says what each number added.

`aerieos-releases` lists the AerieOS releases the catalog serves. The
check holds every entry to each of them that reads a pin of it, so an
entry is signed only when the oldest install that takes it does so as the
newest does; an entry no listed release reads is refused, since nobody
could install it. Adding something written in a format installs already
read needs no release of AerieOS: it is a signed commit here.

The first AerieOS that reads pack format 5 is the oldest release the
catalog serves. The releases before it are off the list, and nothing here
is kept for them.

### An entry's older pins

From that release on, a pack that moves to a newer pack format keeps
serving the installs that read only the one before. Its earlier manifest
is still in its repository at its earlier commit, so the entry keeps that
pin beside the new one, under `older`, newest first:

```json
{"name": "hexkit", "format": 6, "framework": "6.0", "commit": "89ab...", "sha256": "5e1f...", "held": "pinned",
 "older": [
   {"format": 5, "framework": "5.2", "commit": "0123...", "sha256": "9c4d...",
    "platforms": ["linux/amd64"], "held": "pinned"}
 ]}
```

Each install takes the newest pin whose format it reads. An older pin
says everything that moves with a pin (`format`, `framework`, `commit`,
`sha256`, `platforms`, `label`, `works_with`, `held`, `online`, a recipe's
rev) and nothing the entry says once. The tools write it: a pin in a
newer format than the entry's becomes the newest and the one that was
there moves under `older`.

The check holds this from both sides. Every pin is read at its own commit
by each listed release that reads its format. And nothing is taken away
from a listed release: an entry it could take before a change still
answers it a pin after, or is marked withdrawn. A change that would leave
a listed release with nothing is refused.

A pin goes only when no listed release needs it: once the last release
that read only its format is taken off `aerieos-releases`,
`tools/packs-export.py --catalog DIR --drop-older N` drops the pins
written in format N.

### At an AerieOS release

Once a release is out, a maintainer lists it:

```sh
tools/aerieos-release.py v0.9.0
```

It adds the tag to `aerieos-releases` and writes into `index.json`'s
`formats` which AerieOS first reads each pack format that release
brought, read from AerieOS at that tag. `--only` takes every other
release off the list. It signs nothing: the index changed, so the sign
workflow is run for the branch, and the branch merged.

While `aerieos-releases` lists no release, nothing passes for want of
one: the check fails when it is handed no AerieOS and says which command
lists the first, and the pins job says so and does nothing.

## How a pin moves

An install never asks a vendor what is newest. It takes the pin, so a
newer version arrives as a change here, in three steps:

1. **A job proposes.** `.github/workflows/pins.yml` runs once a day and by
   hand. AerieOS's `tools/pins.py --catalog . check`, at the newest release
   listed, asks each pack how its own entry says a newer pin is found (a
   download's `track` and `found`, a recipe's resolver, the registry for an
   image's tag). Where something would move, it moves it, writes the
   entries of the folders that changed, and opens a pull request that says
   what moved from what to what. It moves Aerie's own packs only.
2. **A person reviews.** A maintainer reads what moved.
3. **The sign workflow publishes.** The job holds no key and signs
   nothing. A maintainer runs the sign workflow for the pull request's
   branch, which checks every entry again and commits the signed index,
   and then merges.

The same by hand, from a checkout of AerieOS:

```sh
tools/pins.py --catalog DIR check          # what would move; writes nothing
tools/pins.py --catalog DIR move NAME      # the new version and digests, into the pack
tools/pins.py --catalog DIR verify         # each pinned file fetched and held to its pin
```

then commit the pack, write its entry at that commit
(`tools/packs-export.py --catalog DIR --entry FOLDER`), and commit the
index.

An entry whose manifest says the AerieOS release lines it works with
(`works_with`, e.g. `["0.9", "0.10"]`) repeats the list, and the check holds
the two equal: an install on another line does not show the entry at all,
and one that upgrades past the lines a kept pack names switches that pack
off until a pin that names the new line is kept. A manifest that names none
works with every line, and its entry says nothing.

An entry may name a `path`: the folder of its repository the pack lives
in, for a repository that holds several. Its sha256 is then of that
folder's archive at the commit, and an install keeps the folder's files
and nothing else.

## Submitting a pack

The whole of it, with a worked example of a tool pack, a coding agent and
a Docker app, is [Submitting to the catalog](https://github.com/aquilaelabs/aerieos/blob/main/docs/submitting.md).
In short:

1. Write the pack in the framework (AerieOS's docs/tool-packs.md) and try
   it on an install of your own: the Library's **Add your own** reads it,
   shows what it would fetch and run, and keeps it as Sideloaded.
2. Open a pull request that adds one entry to `index.json`: the pack's
   repository, the commit to pin, and the sha256 of `git archive
   --format=tar COMMIT | sha256sum` at that commit (of the pack's folder,
   with a `path`), with what the manifest says repeated: its `maker`, its
   `format` and `framework`, and `held`, the word **Look** shows for your
   pack. It must read `pinned` or `installer`: declare what your install
   downloads. Never change `index.sig`: it is the maintainers'.
   Your entry and nothing else: a pull request that also touches another
   owner's entry, Aerie's own, or any other file here is refused by the
   check ([Whose an entry is](#whose-an-entry-is)).
3. The vetting check (`.github/workflows/check.yml`,
   `tools/catalog-check.py`) fetches each entry the pull request changes
   at its pin, checks the commit and the sha256, and reads its manifest
   with AerieOS's own readers, so it passes exactly when an install would
   take it. Run it first:

   ```sh
   pip install cryptography
   tools/aerieos-checkouts.sh > /tmp/releases
   mapfile -t releases < /tmp/releases
   python3 tools/catalog-check.py "${releases[@]}" --changed-from origin/main
   ```

4. A maintainer reads what it runs, installs it on every system it names,
   runs AerieOS's scanners over it, marks it vetted, signs the index and
   merges. A push to main checks every entry and the signature.

A pack found wanting later is marked `withdrawn: true` in the next signed
index, and every install that holds it says so on its bell.
