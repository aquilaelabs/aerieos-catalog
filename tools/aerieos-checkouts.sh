#!/usr/bin/env bash
#
# tools/aerieos-checkouts.sh [REF...]
#
# A shallow checkout of AerieOS at every release aerieos-releases lists, and
# at each REF named beside them (a branch that reads a pack format no
# release does yet), under .aerieos/. Prints the words catalog-check.py
# takes for them, one a line: --builderbot, then NAME=DIR.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
repo="${AERIEOS_REPO:-https://github.com/aquilaelabs/aerieos}"

refs=()
while read -r ref _; do
    case "$ref" in ""|"#"*) ;; *) refs+=("$ref") ;; esac
done < "$here/aerieos-releases"
for ref in "$@"; do
    [ -z "$ref" ] || refs+=("$ref")
done

for ref in "${refs[@]}"; do
    [[ "$ref" =~ ^[A-Za-z0-9._/-]{1,100}$ ]] || { echo "not a branch or a tag: $ref" >&2; exit 1; }
    dir="$here/.aerieos/${ref//\//-}"
    [ -d "$dir" ] || git clone --quiet --depth 1 --branch "$ref" "$repo" "$dir"
    printf -- '--builderbot\n%s=%s\n' "$ref" "$dir"
done
