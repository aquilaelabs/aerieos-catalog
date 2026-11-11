#!/bin/sh
# The install counts when the program is there and answers: its version,
# or its help where a release has no such word.
set -eu
dir="$(cd "$(dirname "$0")" && pwd)"
[ -x "$dir/bin/agy" ] || { echo "no agy at $dir/bin" >&2; exit 1; }
"$dir/bin/agy" --version 2>/dev/null || "$dir/bin/agy" --help >/dev/null 2>&1
