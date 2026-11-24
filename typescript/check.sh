#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin typescript
# The standard's own part holds the fixture trees of its S1 harness, which
# typescript_fixtures.py checks as projects of their own and whose breaking
# trees break rules on purpose, so its checks leave them out.
foreign=()
if [ "$(pwd -P)" = "$(cd "$standards" && pwd -P)" ]; then
	foreign=(':!fixtures/')
	mapfile -t tracked < <(git ls-files -- . "${foreign[@]}")
fi
pinned NODE node "nvm install {}, or another way to put Node {} on PATH" node --version
# A check's key holds the pinned version of the tool it runs.
versions=(
	"--tool=format=${pins[BIOME]}"
	"--tool=lint=${pins[BIOME]}"
	"--tool=types=${pins[TYPESCRIPT]}"
	"--tool=unused=${pins[KNIP]}"
)
if full; then
	versions+=("--tool=mutation=${pins[STRYKER]}")
	if [ -e node_modules/@stryker-mutator/core ]; then
		pinned STRYKER node "npm install -D @stryker-mutator/core@{} @stryker-mutator/tap-runner@{}" \
			node -p 'require("./node_modules/@stryker-mutator/core/package.json").version'
	fi
fi
release_versions
units "--toolchain=$(node --version 2>&1)" "${versions[@]}" \
	--project=exceptions,format,lint,types,unused,test,test-release,mutation,duplication,volume

project=$(pwd)
biome=()
if ! biome_config=$(existing biome.json biome.jsonc); then
	biome_config=$standards/biome.json
	biome=(--config-path="$(native "$biome_config")")
fi

mapfile -t sources < <(git ls-files -- '*.ts' '*.tsx' '*.js' '*.mjs' '*.jsx' '*.css' '*.json' "${foreign[@]}" |
	grep -vE '(^|/)(package-lock|tsconfig)\.json$')

# Biome reads a workspace's package.json files only from a config inside the
# project, so the lint config, the project's or the standard's with each
# package's layer rules from biome-layers.json added as overrides, is written
# under node_modules, which git ignores and Biome doesn't scan.
# Biome can only skip all plugins at once, so built-in rules run first with
# plugins skipped, then each plugin runs alone on the files it still covers.
biome_lint() {
	local status=0 skips name path rule layered=node_modules/.cache/standards/biome.json
	local -a fields files skip covered
	mkdir -p "${layered%/*}"
	checks biome-layers "$(native "$biome_config")" "$(native "$standards/biome-layers.json")" 		"$layered" "${sources[@]}" || return 1
	while IFS='|' read -r -a fields; do
		skips=${fields[0]}
		files=("${fields[@]:1}")
		skip=(--skip=plugin)
		for rule in $skips; do
			skip+=(--skip="$rule")
		done
		npx -y "@biomejs/biome@${pins[BIOME]}" lint --config-path="$layered" "${skip[@]}" "${files[@]}" || status=1
	done < <(checks biome-groups "${sources[@]}")
	while IFS='|' read -r name path; do
		mapfile -t covered < <(checks without "lint/plugin/$name" "${sources[@]}")
		((${#covered[@]} > 0)) || continue
		mkdir -p "$logs/plugins/$name"
		printf '{"plugins": ["%s"]}\n' "$path" >"$logs/plugins/$name/biome.json"
		npx -y "@biomejs/biome@${pins[BIOME]}" lint --only=plugin \
			--config-path="$(native "$logs/plugins/$name/biome.json")" "${covered[@]}" || status=1
	done < <(checks biome-plugins "$(native "$biome_config")")
	return "$status"
}

exceptions_unit
unit format "last 'Found [0-9]+ errors?|Checked [0-9]+ files?'" \
	npx -y "@biomejs/biome@${pins[BIOME]}" format "${biome[@]}" "${sources[@]}"
unit lint "joined 'Found [0-9]+ (error|warning|info)s?'" \
	biome_lint
if [ -f tsconfig.json ]; then
	printf '{"extends": ["%s", "%s"], "compilerOptions": {"typeRoots": ["%s"]}}\n' \
		"$(native "$project/tsconfig.json")" \
		"$(native "$standards/tsconfig.base.json")" \
		"$(native "$project/node_modules/@types")" >"$logs/tsconfig.json"
	unit types "count 'error TS' errors" \
		npx -y -p "typescript@${pins[TYPESCRIPT]}" tsc -p "$(native "$logs/tsconfig.json")"
fi
if [ -f package.json ]; then
	unit unused "joined '^(Unused|Unlisted|Duplicate) [^(]+\([0-9]+\)'" \
		npx -y -p "node@${pins[NODE]}" -p "knip@${pins[KNIP]}" knip --no-progress
fi
tests=(test)
test_check=test
if full && grep -qs '"test:full"' package.json; then
	tests=(run test:full)
	test_check=test-release
fi
if grep -qs '"test' package.json && at_least step; then
	unit "$test_check" "joined '(pass|fail) [0-9]+'" npm "${tests[@]}" --silent
fi
if full; then
	mutation=()
	stryker_config=stryker.config.json
	if ! compgen -G 'stryker.conf*' >/dev/null && ! compgen -G 'stryker.config.*' >/dev/null; then
		stryker_config=$standards/stryker.config.json
		mutation=("$(native "$stryker_config")")
	fi
	mutate=$(checks stryker-mutate "$(native "$stryker_config")")
	if [ -n "$mutate" ]; then
		mutation+=(--mutate "$mutate")
	fi
	if dry || [ -e node_modules/@stryker-mutator/core ]; then
		unit mutation "last 'mutation score (of )?[0-9.]+'" \
			npx --no-install stryker run "${mutation[@]}"
	else
		skipped mutation "@stryker-mutator/core not installed"
	fi
	release_units typescript,javascript,css ts,tsx,js,mjs,jsx,css
fi

finish
