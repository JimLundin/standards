#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
cd "${1:-.}" || exit 2
project=$(pwd)
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

native() {
	if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi
}

mapfile -t sources < <(git ls-files '*.ts' '*.tsx' '*.js' '*.mjs' '*.jsx' '*.css' '*.json' |
	grep -vE '(^|/)(package-lock|tsconfig)\.json$')

compiler=$(mktemp -d)
trap 'rm -rf "$compiler"' EXIT
if [ -f tsconfig.json ]; then
	printf '{"extends": ["%s", "%s"], "compilerOptions": {"typeRoots": ["%s"]}}\n' \
		"$(native "$project/tsconfig.json")" \
		"$(native "$standards/tsconfig.base.json")" \
		"$(native "$project/node_modules/@types")" >"$compiler/tsconfig.json"
fi

step format npx -y @biomejs/biome@latest format --config-path="$(native "$standards/biome.json")" "${sources[@]}"
step lint npx -y @biomejs/biome@latest lint --config-path="$(native "$standards/biome.json")" "${sources[@]}"
if [ -f tsconfig.json ]; then
	step types npx -y -p typescript@latest tsc -p "$(native "$compiler/tsconfig.json")"
fi
if [ -f package.json ]; then
	step unused npx -y -p node@26 -p knip@latest knip --no-progress
fi
step duplication npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" --format typescript,javascript,css --silent .
step volume scc --include-ext ts,tsx,js,mjs,jsx,css --no-cocomo .

if ((${#failed[@]})); then
	echo "== failed: ${failed[*]}"
	exit 1
fi
