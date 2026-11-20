#!/bin/sh
# Gemini's program for AerieOS: Google's Antigravity CLI (agy), unpacked from
# the archive the manifest declares for this machine (install.fetch in
# bbtool.json). AerieOS fetched that archive from Google's own storage and
# held it to the sha256 the manifest carries before this ran, so nothing
# here downloads anything: the step runs with no network. A newer release
# is a moved pin in the manifest, vetted and signed in the catalog like any
# other, and never a change to this file.
set -eu

dir="$(cd "$(dirname "$0")" && pwd)"
# A musl system (Alpine) cannot load the glibc build. Its own archive is
# declared beside the other and is here only on such a machine.
archive="$dir/dl/cli.tar.gz"
if [ -f "$dir/dl/cli-musl.tar.gz" ]; then archive="$dir/dl/cli-musl.tar.gz"; fi
[ -f "$archive" ] || { echo "the archive this pack declares for this machine is not at $archive" >&2; exit 1; }

mkdir -p "$dir/bin"
tar -xzf "$archive" -C "$dir/bin" antigravity
mv -f "$dir/bin/antigravity" "$dir/bin/agy"
chmod 0755 "$dir/bin/agy"
rm -f "$dir/dl/cli.tar.gz" "$dir/dl/cli-musl.tar.gz"
echo "Antigravity CLI is at $dir/bin/agy"
