#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
cd "${1:-.}" || exit 2
failed=()

step() {
	local name=$1
	shift
	if ! command -v "$1" >/dev/null; then
		echo "== $name: skipped, $1 not installed"
		return
	fi
	echo "== $name"
	"$@" || failed+=("$name")
}

mapfile -t lints < <(awk '
	/^\[lints\.rust\]/ { prefix = ""; on = 1; next }
	/^\[lints\.clippy\]/ { prefix = "clippy::"; on = 1; next }
	/^\[/ { on = 0 }
	on && match($0, /"(allow|warn|deny|forbid)"/) {
		print "-" toupper(substr($0, RSTART + 1, 1))
		print prefix $1
	}
' "$standards/Cargo.fragment.toml")

step format cargo +nightly fmt --check -- --config-path "$standards/rustfmt.toml"
step lint cargo +nightly clippy --all-targets -- "${lints[@]}"
step test cargo +nightly test --quiet
step unused-dependencies cargo machete
step duplication npx -y jscpd@latest --config "$standards/../jscpd.json" --format rust --silent .
step volume scc --include-ext rs --no-cocomo .

if ((${#failed[@]})); then
	echo "== failed: ${failed[*]}"
	exit 1
fi
