#!/usr/bin/env bash
set -euo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
cd "${1:-.}"
shift $(($# > 0 ? 1 : 0))

export PROPTEST_CASES=${PROPTEST_CASES:-32}
cargo mutants --config "$standards/mutants.toml" "$@"
