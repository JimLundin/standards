#!/usr/bin/env bash
set -euo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
cd "${1:-.}"
shift $(($# > 0 ? 1 : 0))

options=()
if [ ! -e .cargo/mutants.toml ]; then
	options+=(--config "$standards/mutants.toml")
fi
if command -v cargo-nextest >/dev/null; then
	options+=(--test-tool nextest)
fi

export PROPTEST_CASES=${PROPTEST_CASES:-32}
cargo mutants "${options[@]}" "$@"
