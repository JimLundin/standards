#!/usr/bin/env bash
set -euo pipefail

cd "${1:-.}"
shift $(($# > 0 ? 1 : 0))

# MUTATE_WORKDIR runs mutmut in a mirror on a faster filesystem, such as the
# Linux side of WSL for a project on the Windows drive. The mirror keeps .venv
# and mutants/ so mutmut's incremental cache survives between runs.
if [[ -n ${MUTATE_WORKDIR:-} ]]; then
	mirror="$MUTATE_WORKDIR/$(basename "$PWD")"
	mkdir -p "$mirror"
	rsync -a --delete --exclude /.venv --exclude /mutants ./ "$mirror/"
	cd "$mirror"
fi

if (($# > 0)); then
	uv run --frozen -q mutmut "$@"
else
	uv run --frozen -q mutmut run | tr '\r' '\n' | tail -2
	uv run --frozen -q mutmut results
fi
