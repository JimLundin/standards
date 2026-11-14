#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
cd "${1:-.}" || exit 2

mapfile -t lints < <(awk '
	/^\[lints\.rust\]/ { prefix = ""; on = 1; next }
	/^\[lints\.clippy\]/ { prefix = "clippy::"; on = 1; next }
	/^\[/ { on = 0 }
	on && match($0, /"(allow|warn|deny|forbid)"/) {
		print "-" toupper(substr($0, RSTART + 1, 1))
		print prefix $1
	}
' "$standards/Cargo.fragment.toml")

step format "count '^Diff in' differences" \
	cargo +nightly fmt --check -- --config-path "$standards/rustfmt.toml"
step lint "last '[0-9]+ previous errors?|Finished'" \
	cargo +nightly clippy --all-targets -- "${lints[@]}"
step test "summed 'passed|failed'" cargo +nightly test --quiet
step unused-dependencies "last '(didn.t find any|found the following) unused dependencies'" cargo machete
step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
	npx -y jscpd@latest --config "$standards/../jscpd.json" --format rust --silent .
step volume totals scc --include-ext rs --no-cocomo .

finish
