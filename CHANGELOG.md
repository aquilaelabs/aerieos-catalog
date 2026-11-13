# Changelog

## Unreleased

- Whose an entry is: the check says whose each changed entry is, on a pull request (by the copy of the check main has), on a push to main and before the index is signed, and refuses a change that crosses owners: Aerie's own entries and a third party's in one change, two owners' entries in one change, a third party's entry removed, handed to another owner, changed with no new pin beyond withdrawn and tier, or moved beside any other file here. tools/test_whose.py holds the rules; .github/CODEOWNERS names the maintainers for the signature, the key, the tools, the workflows and Aerie's own packs
- The vetting check: tools/catalog-check.py fetches an entry at its pin, checks the commit and its archive's sha256, and holds its manifest (a pack's bbtool.json, an app's bbapp.json and compose.yml) to BuilderBot's own validators, the entry's name and platforms to the manifest's, and an official entry to this repository's own packs; CI runs it on a pull request's changed entries and, with the signature, on every push to main (R169 step 3)
- A Docker app in the catalog, whoami (traefik/whoami, MIT) under packs/apps/whoami, an index entry of kind app naming its folder (R170 step 7)
- The shipped toolchains and coding agents as packs under packs/official and packs/agents, each pinned in the index at tier official with its folder as path (R170 step 6)

### Added

- The signed index: index.json pinning each pack to an exact commit and its archive's sha256, index.sig by the maintainers' Ed25519 key whose public half ships with BuilderBot, and tools/catalog-sign.py to make a key, sign and verify.
