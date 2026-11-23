#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin rust
source "$standards/build.sh"

cargo=(cargo +nightly)
if existing rust-toolchain rust-toolchain.toml >/dev/null; then
	cargo=(cargo)
fi
if ! clippy_config=$(existing clippy.toml .clippy.toml); then
	clippy_config=$standards/clippy.toml
	export CLIPPY_CONF_DIR
	CLIPPY_CONF_DIR=$(native "$standards")
fi
format=()
if ! existing rustfmt.toml .rustfmt.toml >/dev/null; then
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
done < <(checks globs mutation)
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
	checks nextest-config >"$logs/nextest.toml"
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
pinned NEXTEST cargo-nextest "cargo install --locked cargo-nextest@{}" cargo nextest --version
pinned SCCACHE sccache "cargo install --locked sccache@{}" sccache --version
pinned RUST_DECISIONS rust-decisions \
	"cargo install --locked --path $(native "$standards/measure")" rust-decisions --version
# A check's key holds the pinned version of the tool it runs; the
# toolchain's covers rustfmt and clippy.
versions=(
	"--tool=$test_check=${tests[0]} ${pins[NEXTEST]}"
	"--tool=shell=${pins[RUST_DECISIONS]}"
	"--tool=shell-share=${pins[RUST_DECISIONS]}"
)
if full; then
	pinned CARGO_MUTANTS cargo-mutants "cargo install --locked cargo-mutants@{}" cargo mutants --version
	pinned CARGO_MACHETE cargo-machete "cargo install --locked cargo-machete@{}" cargo machete --version
	versions+=(
		"--tool=mutation=${pins[CARGO_MUTANTS]}"
		"--tool=unused-dependencies=${pins[CARGO_MACHETE]}"
	)
fi
release_versions
units "--toolchain=$("${cargo[@]}" -V 2>&1; "${cargo[@]/cargo/rustc}" -V 2>&1)" \
	"${described[@]}" "${versions[@]}" \
	--project=exceptions,format,shell-share,doctest,mutation,unused-dependencies,duplication,volume \
	"--package=lint,core,api,shell,$test_check"

# The package checks run over the whole workspace, so that cargo resolves
# features once and rebuilds only what changed; `-p` would resolve each
# selection's features apart. Their findings are credited to packages by
# file, and cargo's messages of what it built say which packages it reached.
lint() {
	"${cargo[@]}" clippy --workspace --keep-going --all-targets \
		--message-format=json-render-diagnostics -- "${lints[@]}" >"$logs/lint.jsonl"
}

core() {
	local output status=0 packages=() library
	for library in "${libraries[@]}"; do
		packages+=(-p "$library")
	done
	# Lints only report here, so one library's findings don't stop its
	# dependents from building; rust-core decides which of them fail.
	mkdir -p "$logs/core"
	checks core-clippy "$(native "$clippy_config")" "$(native "$logs/core/clippy.toml")" || return
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

api() {
	local library status=0 documented=()
	for library in "${libraries[@]}"; do
		if "${cargo[@]}" rustdoc -q --lib -p "$library" -- -Zunstable-options \
			--output-format json --document-hidden-items; then
			documented+=("$library")
		else
			echo "error: could not document \`$library\`"
			status=1
		fi
	done
	if ((${#documented[@]} > 0)); then
		checks rust-api "$metadata" "${documented[@]}" || status=1
	fi
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

# The shell's share of the project's decisions, a unit of the whole project
# since a change to any package moves it.
shell_share() {
	local roots
	mapfile -t roots < <(checks rust-roots "$metadata")
	rust-decisions "${roots[@]}" >"$logs/share.jsonl" || return
	checks rust-shell-share "$metadata" "$(native "$logs/share.jsonl")"
}

# nextest builds the workspace's tests and runs the unproven packages';
# cargo test can't select packages without -p, so it runs them all.
run_tests() {
	local expression= package
	if [ "${tests[0]}" != nextest ]; then
		"${cargo[@]}" "${tests[@]}" --workspace "${test_options[@]}"
		return
	fi
	for package in "${selected[@]}"; do
		expression+="${expression:+ | }package(=$package)"
	done
	"${cargo[@]}" "${tests[@]}" --workspace ${expression:+-E "$expression"} "${test_options[@]}"
}

tested() {
	local counts flaky
	counts=$(plain "$1" | grep -E '^ *Summary \[' | tail -1 |
		grep -oE '[0-9]+ (passed|failed|flaky|timed out)' | paste -sd ',' - | sed 's/,/, /g')
	flaky=$(plain "$1" | sed -nE 's/^ *FLAKY [0-9]+\/[0-9]+ \[[^]]*\] +//p' | sort -u | paste -sd ',' - | sed 's/,/, /g')
	echo "${counts:-$(summed 'passed|failed' "$1")}${flaky:+ ($flaky)}"
}

exceptions_unit
unit format "count '^Diff in' differences" "${cargo[@]}" fmt --check "${format[@]}"
batch lint "last '[0-9]+ previous errors?|Finished'" lint "${members[@]}"
if ((listed != 0)); then
	line core FAIL "${layering:-cargo metadata failed}"
	failed+=(core)
	skipped api "no libraries"
elif ((${#libraries[@]} == 0)); then
	line core ok "no libraries"
	line api ok "no libraries"
else
	batch core ending core "${libraries[@]}"
	batch api issues api "${libraries[@]}"
fi
if needs rust-decisions shell; then
	batch shell "last 'Found [0-9]+ issues|shell makes .*|no shell'" shell "${members[@]}"
fi
if needs rust-decisions shell-share; then
	unit shell-share "last 'Found [0-9]+ issues|shell makes .*|no shell'" shell_share
fi
if at_least step; then
	batch "$test_check" tested run_tests "${members[@]}"
fi
if full; then
	if [ "${tests[0]}" = nextest ] &&
		find . -path ./target -prune -o -name lib.rs -path '*/src/*' -print | grep -q .; then
		unit doctest "summed 'passed|failed'" "${cargo[@]}" test --doc --quiet
	fi
	if [ -z "$verify" ] && [ ! -f "$logs/shell-files.txt" ] && command -v rust-decisions >/dev/null; then
		shell >/dev/null 2>&1
	fi
	if [ -f "$logs/shell-files.txt" ]; then
		while IFS= read -r file; do
			mutation+=(--exclude "$file")
		done <"$logs/shell-files.txt"
	fi
	if needs cargo-mutants mutation; then
		unit mutation "last '[0-9]+ mutants tested.*|No mutants found.*'" \
			env PROPTEST_CASES=32 "${cargo[@]}" mutants "${mutation[@]}"
	fi
	unit unused-dependencies "last '(didn.t find any|found the following) unused dependencies'" cargo machete
	release_units rust rs
fi

finish
