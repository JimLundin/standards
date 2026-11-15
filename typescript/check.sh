#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
case ${1:-} in fast | full) profile=$1 && shift ;; esac
cd "${1:-.}" || exit 2
project=$(pwd)
biome="$(native "$standards/biome.json")"

mapfile -t sources < <(git ls-files '*.ts' '*.tsx' '*.js' '*.mjs' '*.jsx' '*.css' '*.json' |
	grep -vE '(^|/)(package-lock|tsconfig)\.json$')

step format "last 'Found [0-9]+ errors?|Checked [0-9]+ files?'" \
	npx -y @biomejs/biome@latest format --config-path="$biome" "${sources[@]}"
step lint "joined 'Found [0-9]+ (error|warning|info)s?'" \
	npx -y @biomejs/biome@latest lint --config-path="$biome" "${sources[@]}"
if [ -f tsconfig.json ]; then
	printf '{"extends": ["%s", "%s"], "compilerOptions": {"typeRoots": ["%s"]}}\n' \
		"$(native "$project/tsconfig.json")" \
		"$(native "$standards/tsconfig.base.json")" \
		"$(native "$project/node_modules/@types")" >"$logs/tsconfig.json"
	step types "count 'error TS' errors" \
		npx -y -p typescript@latest tsc -p "$(native "$logs/tsconfig.json")"
fi
if [ -f package.json ]; then
	step unused "joined '^(Unused|Unlisted|Duplicate) [^(]+\([0-9]+\)'" \
		npx -y -p node@26 -p knip@latest knip --no-progress
fi
if grep -qs '"test"' package.json; then
	step test "joined '(pass|fail) [0-9]+'" npm test --silent
fi
if full; then
	if [ -e node_modules/@stryker-mutator/core ]; then
		step mutation "last 'mutation score of [0-9.]+'" npx --no-install stryker run
	else
		line mutation skip "@stryker-mutator/core not installed"
	fi
	step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" \
		--format typescript,javascript,css --silent .
	step volume totals scc --include-ext ts,tsx,js,mjs,jsx,css --no-cocomo .
fi

finish
