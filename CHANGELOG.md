# Changelog

## Unreleased

### Added

- The signed index: index.json pinning each pack to an exact commit and its archive's sha256, index.sig by the maintainers' Ed25519 key whose public half ships with BuilderBot, and tools/catalog-sign.py to make a key, sign and verify.
