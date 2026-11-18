#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin typescript
scope
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
		npx -y @biomejs/biome@latest lint "${biome[@]}" "${skip[@]}" "${files[@]}" || status=1
	done < <(exceptions biome-groups "${sources[@]}")
	while IFS='|' read -r name path; do
		mapfile -t covered < <(exceptions without "lint/plugin/$name" "${sources[@]}")
		((${#covered[@]} > 0)) || continue
		mkdir -p "$logs/plugins/$name"
		printf '{"plugins": ["%s"]}\n' "$path" >"$logs/plugins/$name/biome.json"
		npx -y @biomejs/biome@latest lint --only=plugin \
			--config-path="$(native "$logs/plugins/$name/biome.json")" "${covered[@]}" || status=1
	done < <(exceptions biome-plugins "$(native "$biome_config")")
	return "$status"
}

step exceptions "last 'Found [0-9]+ issues|All checks passed'" \
	exceptions check typescript "$(native "$standards/..")" "${tracked[@]}"
step format "last 'Found [0-9]+ errors?|Checked [0-9]+ files?'" \
	npx -y @biomejs/biome@latest format "${biome[@]}" "${sources[@]}"
step lint "joined 'Found [0-9]+ (error|warning|info)s?'" \
	biome_lint
if [ -f tsconfig.json ] && ! builds; then
	unbuilt types
elif [ -f tsconfig.json ]; then
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
tests=(test)
if full && grep -qs '"test:full"' package.json; then
	tests=(run test:full)
fi
if grep -qs '"test' package.json && at_least step; then
	if builds; then
		step test "joined '(pass|fail) [0-9]+'" npm "${tests[@]}" --silent
	else
		unbuilt test
	fi
fi
if full; then
	mutation=()
	stryker_config=stryker.config.json
	if ! compgen -G 'stryker.conf*' >/dev/null && ! compgen -G 'stryker.config.*' >/dev/null; then
		stryker_config=$standards/stryker.config.json
		mutation=("$(native "$stryker_config")")
	fi
	if [ -n "$(exceptions globs mutation)" ]; then
		mutation+=(--mutate "$(exceptions stryker-mutate "$(native "$stryker_config")")")
	fi
	if ! builds; then
		unbuilt mutation
	elif [ -e node_modules/@stryker-mutator/core ]; then
		step mutation "last 'mutation score (of )?[0-9.]+'" \
			npx --no-install stryker run "${mutation[@]}"
	else
		line mutation skip "@stryker-mutator/core not installed"
	fi
	step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" \
		--format typescript,javascript,css --silent .
	step volume totals scc --exclude-dir .git,mutants,mutants.out,mutants.out.old,.stryker-tmp --include-ext ts,tsx,js,mjs,jsx,css --no-cocomo .
fi

finish
