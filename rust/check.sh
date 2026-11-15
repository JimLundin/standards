#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
cd "${1:-.}" || exit 2

has() {
	local file
	for file in "$@"; do
		[ -e "$file" ] && return 0
	done
	return 1
}

cargo=(cargo +nightly)
if has rust-toolchain rust-toolchain.toml; then
	cargo=(cargo)
fi
if ! has clippy.toml .clippy.toml; then
	export CLIPPY_CONF_DIR
	CLIPPY_CONF_DIR=$(native "$standards")
fi
format=()
if ! has rustfmt.toml .rustfmt.toml; then
	format=(-- --config-path "$(native "$standards/rustfmt.toml")")
fi
lints=()
if ! grep -qsE '^\[(workspace\.)?lints' Cargo.toml; then
	mapfile -t lints < <(awk '
		/^\[lints\.rust\]/ { prefix = ""; on = 1; next }
		/^\[lints\.clippy\]/ { prefix = "clippy::"; on = 1; next }
		/^\[/ { on = 0 }
		on && match($0, /"(allow|warn|deny|forbid)"/) {
			print "-" toupper(substr($0, RSTART + 1, 1))
			print prefix $1
		}
	' "$standards/Cargo.fragment.toml")
fi

step format "count '^Diff in' differences" "${cargo[@]}" fmt --check "${format[@]}"
step lint "last '[0-9]+ previous errors?|Finished'" \
	"${cargo[@]}" clippy --all-targets -- "${lints[@]}"
if command -v cargo-nextest >/dev/null; then
	step test "summed 'passed|failed'" \
		"${cargo[@]}" nextest run --no-tests=warn --hide-progress-bar
	if find . -path ./target -prune -o -name lib.rs -path '*/src/*' -print | grep -q .; then
		step doctest "summed 'passed|failed'" "${cargo[@]}" test --doc --quiet
	fi
else
	step test "summed 'passed|failed'" "${cargo[@]}" test --quiet
fi
step unused-dependencies "last '(didn.t find any|found the following) unused dependencies'" cargo machete
step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
	npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" --format rust --silent .
step volume totals scc --include-ext rs --no-cocomo .

finish
