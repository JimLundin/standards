#!/usr/bin/env bash
set -euo pipefail

project=$(cd "${1:-.}" && pwd)
shift $(($# > 0 ? 1 : 0))

linux_path() {
	cygpath -u "$1" | sed -E 's|^/([a-z])/|/mnt/\1/|'
}

case "$(uname -s)" in
MINGW* | MSYS* | CYGWIN*)
	MSYS2_ARG_CONV_EXCL='*' exec wsl.exe -e bash -lc 'bash "$0" "$@"' \
		"$(linux_path "$0")" "$(linux_path "$project")" "$@"
	;;
esac

# Running on the Windows drive from WSL is several times slower, so work in
# a mirror on the Linux filesystem; it keeps .venv and mutants/ between runs
# for mutmut's incremental cache.
if [[ $project == /mnt/* ]]; then
	mirror="$HOME/.cache/mutate/$(basename "$project")"
	mkdir -p "$mirror"
	rsync -a --delete --exclude /.venv --exclude /mutants "$project/" "$mirror/"
	cd "$mirror"
else
	cd "$project"
fi

if (($# > 0)); then
	uv run --frozen -q mutmut "$@"
else
	uv run --frozen -q mutmut run | tr '\r' '\n' | tail -2
	uv run --frozen -q mutmut results
fi
