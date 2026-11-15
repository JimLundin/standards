#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
case ${1:-} in fast | full) profile=$1 && shift ;; esac
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

if full; then
	export PROPTEST_CASES=1024
elif ! grep -qs PROPTEST_CASES .cargo/config.toml; then
	export PROPTEST_CASES=16
fi
mutation=()
if [ ! -e .cargo/mutants.toml ]; then
	mutation+=(--config "$(native "$standards/mutants.toml")")
	if ! grep -qs '^\[profile\.mutants\]' Cargo.toml; then
		mutation+=(--profile test)
	fi
fi
tests=()
if command -v cargo-nextest >/dev/null; then
	tests=(nextest run --no-tests=warn --hide-progress-bar)
	mutation+=(--test-tool nextest)
	if full; then
		tests+=(--no-fail-fast --run-ignored all)
	fi
else
	tests=(test --quiet)
	if full; then
		tests+=(--no-fail-fast -- --include-ignored)
	fi
fi

step format "count '^Diff in' differences" "${cargo[@]}" fmt --check "${format[@]}"
step lint "last '[0-9]+ previous errors?|Finished'" \
	"${cargo[@]}" clippy --all-targets -- "${lints[@]}"
step test "summed 'passed|failed'" "${cargo[@]}" "${tests[@]}"
if full; then
	if [ "${tests[0]}" = nextest ] &&
		find . -path ./target -prune -o -name lib.rs -path '*/src/*' -print | grep -q .; then
		step doctest "summed 'passed|failed'" "${cargo[@]}" test --doc --quiet
	fi
	if command -v cargo-mutants >/dev/null; then
		step mutation "last '[0-9]+ mutants tested.*'" \
			env PROPTEST_CASES=32 "${cargo[@]}" mutants "${mutation[@]}"
	else
		line mutation skip "cargo-mutants not installed"
	fi
	step unused-dependencies "last '(didn.t find any|found the following) unused dependencies'" cargo machete
	step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" --format rust --silent .
	step volume totals scc --include-ext rs --no-cocomo .
fi

finish
