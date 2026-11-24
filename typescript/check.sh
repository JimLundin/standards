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
own=
if [ "$(pwd -P)" = "$(cd "$standards" && pwd -P)" ]; then
	own=1
	foreign=(':!fixtures/')
	mapfile -t tracked < <(git ls-files -- . "${foreign[@]}")
fi
pinned NODE node "nvm install {}, or another way to put Node {} on PATH" node --version
# A check's key holds the pinned version of the tool it runs.
versions=(
	"--tool=format=${pins[BIOME]}"
	"--tool=lint=${pins[BIOME]},${pins[OXLINT]},${pins[OXLINT_TSGOLINT]},${pins[CLOUDFLARE_OXLINT_CONFIG]}"
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
mapfile -t scripts < <(printf '%s\n' "${sources[@]}" | grep -E '\.(ts|tsx|js|mjs|jsx)$')

# Oxlint, its type-aware backend and cloudflare's config are installed at
# their pins once, into the cache. A project's oxlint.config.ts runs in
# place. The standard's imports cloudflare's config, so it runs from a copy
# beside that install, outside node_modules, where Node won't strip types.
oxlint_lint() {
	local install run tsgolint typed= status
	((${#scripts[@]} > 0)) || return 0
	install="$(cache_root)/oxlint/${pins[OXLINT]}-${pins[OXLINT_TSGOLINT]}-${pins[CLOUDFLARE_OXLINT_CONFIG]}"
	if [ ! -e "$install/node_modules/oxlint/package.json" ]; then
		mkdir -p "${install%/*}"
		run=$(mktemp -d "$install.XXXXXX")
		printf '{"private": true, "type": "module"}\n' >"$run/package.json"
		npm install --prefix "$(native "$run")" --no-audit --no-fund --loglevel=error \
			"oxlint@${pins[OXLINT]}" "oxlint-tsgolint@${pins[OXLINT_TSGOLINT]}" \
			"@cloudflare/oxlint-config@${pins[CLOUDFLARE_OXLINT_CONFIG]}" || return 1
		if [ -e "$install" ]; then rm -rf "$run"; else mv "$run" "$install"; fi
	fi
	tsgolint=$(cd "$install" && node -p \
		'require.resolve(`@oxlint-tsgolint/${process.platform}-${process.arch}/tsgolint${process.platform === "win32" ? ".exe" : ""}`)') ||
		return 1
	run=$(mktemp -d "$install/run.XXXXXX")
	if [ -n "$own" ] || ! oxlint_config=$(existing oxlint.config.ts); then
		cp "$standards/oxlint.config.ts" "$run/oxlint.config.ts"
		oxlint_config=$run/oxlint.config.ts
	fi
	# Without a tsconfig.json there are no types to check, as for the types
	# unit, so the type-aware rules are off.
	if [ ! -f tsconfig.json ]; then
		cat >"$run/untyped.mjs" <<-'EOF'
			import { pathToFileURL } from "node:url";
			const { default: config } = await import(pathToFileURL(process.env.OXLINT_CONFIG).href);
			export default { ...config, options: { ...config.options, typeAware: false } };
		EOF
		typed=$oxlint_config
		oxlint_config=$run/untyped.mjs
	fi
	# The exceptions turn their rules off for their paths, as overrides of a
	# config that extends this one.
	mkdir -p node_modules/.cache/standards
	oxlint_config=$(checks oxlint-config "$(native "$oxlint_config")") || return 1
	OXLINT_CONFIG=${typed:+$(native "$typed")} OXLINT_TSGOLINT_PATH=$tsgolint \
		node "$(native "$install/node_modules/oxlint/bin/oxlint")" --config="$(native "$oxlint_config")" "${scripts[@]}"
	status=$?
	rm -rf "$run"
	return "$status"
}

# Oxlint runs the rules, and Biome each GritQL plugin alone on the files it
# still covers, as Biome can only skip all plugins at once.
lint() {
	local status=0 name path
	local -a covered
	oxlint_lint || status=1
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
unit lint "joined 'Found [0-9]+ (warnings? and [0-9]+ )?(error|warning|info)s?'" \
	lint
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
