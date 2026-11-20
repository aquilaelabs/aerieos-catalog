#!/usr/bin/env bash
#
# tools/aerieos-checkouts.sh [--only] [REF...]
#
# A shallow checkout of AerieOS at every release aerieos-releases lists, and
# at each REF named beside them (a branch that reads a pack format no
# release does yet). Prints the words catalog-check.py takes for them, one
# a line: --builderbot, then NAME=DIR. The releases come oldest first, as
# the file lists them, so the last pair printed for a release is the newest.
#
# --only leaves the listed releases out: the REFs named, alone.
#
# With no release listed and no REF named there is nothing to check out:
# it says so, prints nothing and ends 3, so what reads its words is handed
# none and says the same (catalog-check.py fails with no AerieOS named).
#
# The checkouts are kept outside this tree, under the account's cache
# (AERIEOS_CHECKOUTS names another place): thousands of files that are not
# the catalog's, which a tree that is synced or watched should not carry.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
repo="${AERIEOS_REPO:-https://github.com/aquilaelabs/aerieos}"
keep="${AERIEOS_CHECKOUTS:-${XDG_CACHE_HOME:-$HOME/.cache}/aerieos-catalog/checkouts}"

only=""
if [ "${1:-}" = "--only" ]; then only=1; shift; fi

refs=()
if [ -z "$only" ]; then
    while read -r ref _; do
        case "$ref" in ""|"#"*) ;; *) refs+=("$ref") ;; esac
    done < "$here/aerieos-releases"
fi
for ref in "$@"; do
    [ -z "$ref" ] || refs+=("$ref")
done

if [ "${#refs[@]}" = 0 ]; then
    echo "no AerieOS release is listed yet (aerieos-releases): name the first with tools/aerieos-release.py TAG once it is out, or a branch or tag of AerieOS here as REF" >&2
    exit 3
fi

mkdir -p "$keep"
for ref in "${refs[@]}"; do
    [[ "$ref" =~ ^[A-Za-z0-9._/-]{1,100}$ ]] || { echo "not a branch or a tag: $ref" >&2; exit 1; }
    dir="$keep/${ref//\//-}"
    [ -d "$dir" ] || git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$ref" "$repo" "$dir"
    printf -- '--builderbot\n%s=%s\n' "$ref" "$dir"
done
