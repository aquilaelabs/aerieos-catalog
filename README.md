# builderbot-catalog

The vetted catalog of tool packs and agent packs for BuilderBot (R169):
a searchable list people install from like an app, vetted by BuilderBot's
maintainers. This repository holds the index and its signature; the packs
themselves live in their own repositories, each pinned here to an exact
commit and the sha256 of its archive at that commit, never latest.

- `index.json`: the entries. `{version: 1, generated, packs: [{name, url,
  commit, sha256, tier, withdrawn, about, platforms}]}`.
- `index.sig`: an Ed25519 signature over `index.json`'s bytes by the
  maintainers' key. The public half (`catalog.pub`) ships with BuilderBot
  (its `config/catalog.pub`), so an index tampered with on the way is
  refused by every install.
- `tools/catalog-sign.py`: `keygen`, `sign` and `verify`. The private half
  is a maintainer's own and is never in this repository's files: it is kept
  in the repository's secret `CATALOG_SIGNING_KEY`, and the `sign` workflow,
  run by hand on the branch that holds a changed index, checks every entry,
  signs the index with it and commits `index.sig` to that branch.
  `catalog.pub` may name a spare key on a second line: its private half is
  kept apart from that secret, an install reads an index signed by either,
  and so the first key can be lost or replaced with no install cut off.
- `packs/official/NAME` and `packs/agents/NAME`: every toolchain and
  coding agent BuilderBot ships, as a pack in bbtool.json's format, written
  by BuilderBot's `tools/packs-export.py --catalog` from its own tables so
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
  media, platforms, license) with its `compose.yml` beside it, every image
  pinned to a tag and `${PORT}`, `${DATA}`, `${MEDIA}`, `${PUID}`,
  `${PGID}` and `${TZ}` the only blanks, which New container fills on the
  node picked; its index entry carries `"kind": "app"`. `packs/apps/whoami`
  (traefik/whoami, MIT) is the one to prove a deploy with.
- `packs/`: community manifests under review too, one folder per
  submission, before an entry pins them in the index.

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
past the first. An install too old for an entry lists its card with what it
needs and fetches nothing. AerieOS's `docs/tool-packs.md` says what each
number added.

`aerieos-releases` lists the AerieOS releases the catalog still supports.
The check holds every entry to each of them that reads its format, so an
entry is signed only when the oldest install that takes it does so as the
newest does; an entry no listed release reads is refused, since nobody
could install it. Adding something written in a format installs already
read needs no release of AerieOS: it is a signed commit here.

An entry may name a `path`: the folder of its repository the pack lives
in, for a repository that holds several. Its sha256 is then of that
folder's archive at the commit, and an install keeps the folder's files
and nothing else.

## Submitting a pack

Open a pull request that adds an entry to `index.json`: the pack's
repository, the commit to pin, and the sha256 of `git archive --format=tar
COMMIT | sha256sum` at that commit. The vetting check
(`.github/workflows/check.yml`, `tools/catalog-check.py`) fetches each entry
the pull request changes at its pin, checks the commit and the sha256, and
holds its manifest to BuilderBot's own validators, so it passes exactly when
an install would take it. Run it before opening the request with
`tools/aerieos-checkouts.sh` and `tools/catalog-check.py --builderbot
NAME=DIR ... --changed-from origin/main`, one `--builderbot` for each
release the first prints. A push to main checks every entry and the signature. Installing
the pack on every vetted system and running BuilderBot's scanners over it
come next; a maintainer
reviews it, marks it vetted, signs the index and merges. A pack found
wanting later is marked `withdrawn: true` in the next signed index, and
every install that holds it says so on its bell.
