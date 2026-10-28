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
- `packs/`: community manifests under review, one folder per submission,
  before an entry pins them in the index.

## Submitting a pack

Open a pull request that adds an entry to `index.json`: the pack's
repository, the commit to pin, and the sha256 of `git archive --format=tar
COMMIT | sha256sum` at that commit. The vetting CI installs the pack on
every vetted system and runs BuilderBot's scanners over it; a maintainer
reviews it, marks it vetted, signs the index and merges. A pack found
wanting later is marked `withdrawn: true` in the next signed index, and
every install that holds it says so on its bell.
