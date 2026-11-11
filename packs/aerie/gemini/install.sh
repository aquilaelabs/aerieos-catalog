#!/bin/sh
# Gemini's program for AerieOS: Google's Antigravity CLI (agy) at one release,
# fetched from Google's own storage and held to the sha512 Google's release
# manifest gave for it on the day this pack was vetted
# (https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/PLATFORM.json).
# A newer release is a change to the four lines below, vetted and signed in
# the catalog like any other: nothing here asks what the newest is.
set -eu

VERSION="1.5.6"
BASE="https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.6-6212266538958848"

dir="$(cd "$(dirname "$0")" && pwd)"
musl=""
if [ -f /lib/libc.musl-x86_64.so.1 ] || [ -f /lib/libc.musl-aarch64.so.1 ]; then musl=1; fi
case "$(uname -m):$musl" in
    x86_64:|amd64:)
        url="$BASE/linux-x64/cli_linux_x64.tar.gz"
        sum="0c67824908caf9cc3156699802b8097f2fd02c4608ae9293c9aa7f17e1bcd342c4b9c2e158388253a37804ef6bd9c6b1d25cfaca3c07bbb7587378fc91839bb4" ;;
    aarch64:|arm64:)
        url="$BASE/linux-arm/cli_linux_arm64.tar.gz"
        sum="ed103a9e2f10d99eaf2988d2ace55ffffa08b6f9d3b2297459dc42617dfa2386ed984b1231efda4d93279a1deaab9a7e51b85ed06938527870aaec21bba27254" ;;
    x86_64:1|amd64:1)
        url="$BASE/linux-x64-musl/cli_linux_x64_musl.tar.gz"
        sum="fddcc0393a24704033b977cef4f500bef3c944eec518b718721ba983a4f3dba35a170651a9d17a447e550a1c9cc50c3946416966ed414aa720b0c5121e5fa970" ;;
    aarch64:1|arm64:1)
        url="$BASE/linux-arm-musl/cli_linux_arm64_musl.tar.gz"
        sum="9c4300ff973c0a6697b06a160d98992704e817b1456fe7f7111124e55867a8811dd85d1fb69fa71a9d8aebb467f7c53d7a7b58326d58f81fe6469ef945a5a95f" ;;
    *)
        echo "Antigravity CLI has no build for $(uname -m)" >&2
        exit 1 ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "fetching Antigravity CLI $VERSION"
curl -fsSL --retry 3 -o "$tmp/cli.tar.gz" "$url"
got="$(sha512sum "$tmp/cli.tar.gz" | cut -d' ' -f1)"
if [ "$got" != "$sum" ]; then
    echo "the download is not the release this pack pins: its sha512 is $got" >&2
    exit 1
fi
tar -xzf "$tmp/cli.tar.gz" -C "$tmp" antigravity
mkdir -p "$dir/bin"
install -m 0755 "$tmp/antigravity" "$dir/bin/agy"
echo "$VERSION" > "$dir/VERSION"
echo "Antigravity CLI $VERSION is at $dir/bin/agy"
