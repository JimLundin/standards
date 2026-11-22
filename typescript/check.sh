#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin typescript
pinned NODE node "nvm install {}, or another way to put Node {} on PATH" node --version
# A check's key holds the pinned version of the tool it runs.
versions=(
	"--tool=format=${pins[BIOME]}"
	"--tool=lint=${pins[BIOME]}"
	"--tool=types=${pins[TYPESCRIPT]}"
	"--tool=unused=${pins[KNIP]}"
)
if full; then
	pinned SCC scc "go install github.com/boyter/scc/v3@v{}" scc --version
	versions+=("--tool=duplication=${pins[JSCPD]}" "--tool=volume=${pins[SCC]}")
fi
units "--toolchain=$(node --version 2>&1)" "${versions[@]}" \
	--project=exceptions,format,lint,types,unused,test,test-release,mutation,duplication,volume

project=$(pwd)
biome=()
biome_config=$standards/biome.json
for name in biome.json biome.jsonc; do
	[ -e "$name" ] && biome_config=$name
done
if [ "$biome_config" = "$standards/biome.json" ]; then
	biome=(--config-path="$(native "$biome_config")")
fi

mapfile -t sources < <(git ls-files '*.ts' '*.tsx' '*.js' '*.mjs' '*.jsx' '*.css' '*.json' |
	grep -vE '(^|/)(package-lock|tsconfig)\.json$')
mapfile -t tracked < <(git ls-files)

# Biome can only skip all plugins at once, so built-in rules run first with
# plugins skipped, then each plugin runs alone on the files it still covers.
biome_lint() {
	local status=0 skips name path rule
	local -a fields files skip covered
	while IFS='|' read -r -a fields; do
		skips=${fields[0]}
		files=("${fields[@]:1}")
		skip=(--skip=plugin)
		for rule in $skips; do
			skip+=(--skip="$rule")
		done
		npx -y "@biomejs/biome@${pins[BIOME]}" lint "${biome[@]}" "${skip[@]}" "${files[@]}" || status=1
	done < <(tool_config biome-groups "${sources[@]}")
	while IFS='|' read -r name path; do
		mapfile -t covered < <(tool_config without "lint/plugin/$name" "${sources[@]}")
		((${#covered[@]} > 0)) || continue
		mkdir -p "$logs/plugins/$name"
		printf '{"plugins": ["%s"]}\n' "$path" >"$logs/plugins/$name/biome.json"
		npx -y "@biomejs/biome@${pins[BIOME]}" lint --only=plugin \
			--config-path="$(native "$logs/plugins/$name/biome.json")" "${covered[@]}" || status=1
	done < <(tool_config biome-plugins "$(native "$biome_config")")
	return "$status"
}

unit exceptions "last 'Found [0-9]+ issues|All checks passed'" \
	checks policy typescript "$(native "$standards/..")" "${tracked[@]}"
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
	mutate=$(tool_config stryker-mutate "$(native "$stryker_config")")
	if [ -n "$mutate" ]; then
		mutation+=(--mutate "$mutate")
	fi
	if [ -e node_modules/@stryker-mutator/core ]; then
		unit mutation "last 'mutation score (of )?[0-9.]+'" \
			npx --no-install stryker run "${mutation[@]}"
	else
		line mutation skip "@stryker-mutator/core not installed"
	fi
	unit duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y "jscpd@${pins[JSCPD]}" --config "$(native "$standards/../jscpd.json")" \
		--format typescript,javascript,css --silent .
	unit volume totals scc --exclude-dir .git,mutants,mutants.out,mutants.out.old,.stryker-tmp --include-ext ts,tsx,js,mjs,jsx,css --no-cocomo .
fi

finish
