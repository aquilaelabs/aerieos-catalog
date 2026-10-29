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
  is a maintainer's own and is never in this repository.
- `packs/official/NAME` and `packs/agents/NAME`: every toolchain and
  coding agent BuilderBot ships, as a pack in bbtool.json's format, written
  by BuilderBot's `tools/packs-export.py --catalog` from its own tables so
  the two cannot drift; each has an entry in the index at tier `official`,
  pinned to this repository's commit with its folder as `path` and the
  sha256 of `git archive --format=tar COMMIT PATH`. An install lists them
  on its Library as the shipped rows they are, and the index says which
  commit of the catalog vetted them.
- `packs/apps/NAME`: a Docker app, `bbapp.json` (name, label, about, port,
  media, platforms, license) with its `compose.yml` beside it, every image
  pinned to a tag and `${PORT}`, `${DATA}`, `${MEDIA}`, `${PUID}`,
  `${PGID}` and `${TZ}` the only blanks, which New container fills on the
  node picked; its index entry carries `"kind": "app"`. `packs/apps/whoami`
  (traefik/whoami, MIT) is the one to prove a deploy with.
- `packs/`: community manifests under review too, one folder per
  submission, before an entry pins them in the index.

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
`tools/catalog-check.py --builderbot PATH-TO-BUILDERBOT --changed-from
origin/main`. A push to main checks every entry and the signature. Installing
the pack on every vetted system and running BuilderBot's scanners over it
come next; a maintainer
reviews it, marks it vetted, signs the index and merges. A pack found
wanting later is marked `withdrawn: true` in the next signed index, and
every install that holds it says so on its bell.
