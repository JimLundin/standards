#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin rust
source "$standards/build.sh"

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
done < <(tool_config globs mutation)
mapfile -t tracked < <(git ls-files)
core_target=wasm32v1-none

metadata=$(native "$logs/metadata.json")
listed=1
libraries=()
described=()
if "${cargo[@]}" metadata --no-deps --format-version 1 >"$logs/metadata.json"; then
	layering=$(checks core-libraries "$metadata")
	listed=$?
	mapfile -t libraries < <(grep . <<<"$layering")
	described=("--metadata=$metadata")
fi

tests=(test)
test_options=(--quiet)
if command -v cargo-nextest >/dev/null; then
	tests=(nextest run)
	test_options=(--no-fail-fast --no-tests=warn --hide-progress-bar)
	tool_config nextest-config >"$logs/nextest.toml"
	if [ -s "$logs/nextest.toml" ]; then
		test_options+=(--tool-config-file "standards:$(native "$logs/nextest.toml")")
	fi
	mutation+=(--test-tool nextest)
	if full; then
		test_options+=(--run-ignored all)
	fi
elif full; then
	test_options+=(--no-fail-fast -- --include-ignored)
fi
test_check=test
if full; then
	test_check=test-release
fi
units "--toolchain=$("${cargo[@]}" -V 2>&1)" "${described[@]}" \
	--project=exceptions,format,shell,doctest,mutation,unused-dependencies,duplication,volume \
	"--package=lint,core,api,$test_check"

chosen() {
	local package
	for package in "${selected[@]}"; do
		printf '%s\n' -p "$package"
	done
}

lint() {
	local packages
	mapfile -t packages < <(chosen)
	"${cargo[@]}" clippy --keep-going --all-targets "${packages[@]}" -- "${lints[@]}"
}

core() {
	local output status=0 packages
	mapfile -t packages < <(chosen)
	# Lints only report here, so one library's findings don't stop its
	# dependents from building; rust-core decides which of them fail.
	mkdir -p "$logs/core"
	checks core-clippy "$(native "$(clippy_config)")" "$(native "$logs/core/clippy.toml")" || return
	output=$(CLIPPY_CONF_DIR=$(native "$logs/core") "${cargo[@]}" clippy --keep-going --lib \
		--target "$core_target" --all-features --message-format=json \
		"${packages[@]}" -- --cap-lints warn 2>&1 >"$logs/core.jsonl") || status=$?
	echo "$output"
	if grep -q 'may not be installed' <<<"$output"; then
		echo "rustup target add $core_target"
		return "$status"
	fi
	checks rust-core "$metadata" "$(native "$logs/core.jsonl")" "${tracked[@]}" || status=1
	if grep -q 'could not compile' <<<"$output"; then
		echo "uses std: $(grep -oE 'could not compile `[^`]+`' <<<"$output" |
			cut -d'`' -f2 | sort -u | paste -sd ' ' -)"
	fi
	return "$status"
}

clippy_config() {
	local file
	for file in clippy.toml .clippy.toml; do
		if [ -e "$file" ]; then
			echo "$file"
			return
		fi
	done
	echo "$standards/clippy.toml"
}

api() {
	local library status=0
	: >"$logs/api.passed"
	for library in "${selected[@]}"; do
		if "${cargo[@]}" rustdoc -q --lib -p "$library" -- -Zunstable-options \
			--output-format json --document-hidden-items &&
			checks rust-api "$metadata" "$library"; then
			echo "$library" >>"$logs/api.passed"
		else
			status=1
		fi
	done
	return "$status"
}

issues() {
	local found
	found=$(summed issues "$1")
	echo "${found:-$(ending "$1")}"
}

shell() {
	local roots
	mapfile -t roots < <(checks rust-roots "$metadata")
	rust-decisions "${roots[@]}" >"$logs/decisions.jsonl" || return
	checks rust-shell "$metadata" \
		"$(native "$logs/decisions.jsonl")" "$(native "$logs/shell-files.txt")"
}

run_tests() {
	local packages
	mapfile -t packages < <(chosen)
	"${cargo[@]}" "${tests[@]}" "${packages[@]}" "${test_options[@]}"
}

tested() {
	local counts flaky
	counts=$(plain "$1" | grep -E '^ *Summary \[' | tail -1 |
		grep -oE '[0-9]+ (passed|failed|flaky|timed out)' | paste -sd ',' - | sed 's/,/, /g')
	flaky=$(plain "$1" | sed -nE 's/^ *FLAKY [0-9]+\/[0-9]+ \[[^]]*\] +//p' | sort -u | paste -sd ',' - | sed 's/,/, /g')
	echo "${counts:-$(summed 'passed|failed' "$1")}${flaky:+ ($flaky)}"
}

unit exceptions "last 'Found [0-9]+ issues|All checks passed'" \
	checks policy rust "$(native "$standards/..")" "${tracked[@]}"
unit format "count '^Diff in' differences" "${cargo[@]}" fmt --check "${format[@]}"
batch lint "last '[0-9]+ previous errors?|Finished'" lint "${members[@]}"
if ((listed != 0)); then
	line core FAIL "${layering:-cargo metadata failed}"
	failed+=(core)
	line api skip "no libraries"
elif ((${#libraries[@]} == 0)); then
	line core ok "no libraries"
	line api ok "no libraries"
else
	batch core ending core "${libraries[@]}"
	batch api issues api "${libraries[@]}"
fi
if command -v rust-decisions >/dev/null; then
	unit shell "last 'Found [0-9]+ issues|shell makes .*|no shell'" shell
else
	line shell skip "rust-decisions not installed"
fi
if at_least step; then
	batch "$test_check" tested run_tests "${members[@]}"
fi
if full; then
	if [ "${tests[0]}" = nextest ] &&
		find . -path ./target -prune -o -name lib.rs -path '*/src/*' -print | grep -q .; then
		unit doctest "summed 'passed|failed'" "${cargo[@]}" test --doc --quiet
	fi
	if [ ! -f "$logs/shell-files.txt" ] && command -v rust-decisions >/dev/null; then
		shell >/dev/null 2>&1
	fi
	if [ -f "$logs/shell-files.txt" ]; then
		while IFS= read -r file; do
			mutation+=(--exclude "$file")
		done <"$logs/shell-files.txt"
	fi
	if command -v cargo-mutants >/dev/null; then
		unit mutation "last '[0-9]+ mutants tested.*|No mutants found.*'" \
			env PROPTEST_CASES=32 "${cargo[@]}" mutants "${mutation[@]}"
	else
		line mutation skip "cargo-mutants not installed"
	fi
	unit unused-dependencies "last '(didn.t find any|found the following) unused dependencies'" cargo machete
	unit duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" --format rust --silent .
	unit volume totals scc --exclude-dir .git,mutants,mutants.out,mutants.out.old,.stryker-tmp --include-ext rs --no-cocomo .
fi

finish
