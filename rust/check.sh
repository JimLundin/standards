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
while IFS= read -r glob; do
	mutation+=(--exclude "$glob")
done < <(exceptions globs mutation)
mapfile -t tracked < <(git ls-files)
core_target=wasm32v1-none

ending() {
	plain "$1" | tail -1
}

metadata=$(native "$logs/metadata.json")
listed=1
libraries=()
if "${cargo[@]}" metadata --no-deps --format-version 1 >"$logs/metadata.json"; then
	listing=$(exceptions core-libraries "$metadata")
	listed=$?
	mapfile -t libraries < <(grep . <<<"$listing")
fi

core() {
	local output status=0 library packages=()
	if ((listed != 0)); then
		echo "${listing:-cargo metadata failed}"
		return 1
	fi
	if ((${#libraries[@]} == 0)); then
		echo "no libraries"
		return
	fi
	for library in "${libraries[@]}"; do
		packages+=(-p "$library")
	done
	output=$("${cargo[@]}" check --lib --target "$core_target" \
		"${packages[@]}" 2>&1) || status=$?
	echo "$output"
	if ((status == 0)); then
		echo "no_std: ${libraries[*]}"
	elif grep -q 'may not be installed' <<<"$output"; then
		echo "rustup target add $core_target"
	else
		echo "uses std: $(grep -oE 'could not compile `[^`]+`' <<<"$output" |
			cut -d'`' -f2 | sort -u | paste -sd ' ' -)"
	fi
	return "$status"
}

api() {
	local library skips=()
	if ((listed != 0 || ${#libraries[@]} == 0)); then
		echo "no libraries"
		return
	fi
	for library in "${libraries[@]}"; do
		"${cargo[@]}" rustdoc -q --lib -p "$library" -- -Zunstable-options \
			--output-format json --document-hidden-items || return
	done
	while IFS= read -r glob; do
		skips+=("--skip=$glob")
	done < <(exceptions globs api)
	checks rust-api "${skips[@]}" "$metadata" "${libraries[@]}"
}

shell() {
	local target skips=() targets=(--bins)
	if ! grep -qE '"kind":\[[^]]*"bin"' "$logs/metadata.json"; then
		echo "no binaries"
		return
	fi
	if grep -qE '"kind":\[[^]]*"r?lib"' "$logs/metadata.json"; then
		targets+=(--lib)
	fi
	target=$(sed -E 's/.*"target_directory":"([^"]*)".*/\1/; s#\\\\#/#g' \
		"$logs/metadata.json")
	CLIPPY_CONF_DIR=$(native "$standards/measure") "${cargo[@]}" clippy \
		--workspace "${targets[@]}" --target-dir "${target:-target}/shell" \
		--message-format=json -- --cap-lints warn -W clippy::cognitive_complexity \
		>"$logs/complexity.jsonl" || return
	while IFS= read -r glob; do
		skips+=("--skip=$glob")
	done < <(exceptions globs shell)
	checks rust-shell "${skips[@]}" \
		"$(native "$logs/complexity.jsonl")" "$(native "$logs/shell-files.txt")"
}

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

step exceptions "last 'Found [0-9]+ issues|All checks passed'" \
	exceptions check rust "$(native "$standards/..")" "${tracked[@]}"
step format "count '^Diff in' differences" "${cargo[@]}" fmt --check "${format[@]}"
step lint "last '[0-9]+ previous errors?|Finished'" \
	"${cargo[@]}" clippy --all-targets -- "${lints[@]}"
step core ending core
step api "last 'Found [0-9]+ issues|All checks passed|no libraries'" api
step shell "last 'Found [0-9]+ issues|shell makes .*|no binaries'" shell
step test "summed 'passed|failed'" "${cargo[@]}" "${tests[@]}"
if full; then
	if [ "${tests[0]}" = nextest ] &&
		find . -path ./target -prune -o -name lib.rs -path '*/src/*' -print | grep -q .; then
		step doctest "summed 'passed|failed'" "${cargo[@]}" test --doc --quiet
	fi
	if [ -f "$logs/shell-files.txt" ]; then
		while IFS= read -r file; do
			mutation+=(--exclude "$file")
		done <"$logs/shell-files.txt"
	fi
	if command -v cargo-mutants >/dev/null; then
		step mutation "last '[0-9]+ mutants tested.*|No mutants found.*'" \
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
