#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
arguments "$@"
cd "$project" || exit 2
begin typescript
# The standard's own part holds the fixture trees of its S1 harness, which
# typescript_fixtures.py checks as projects of their own and whose breaking
# trees break rules on purpose, and the oxlint-plugins package, a part of its
# own, so its checks leave them out.
foreign=()
own=
if [ "$(pwd -P)" = "$(cd "$standards" && pwd -P)" ]; then
	own=1
	foreign=(':!fixtures/' ':!oxlint-plugins/')
	mapfile -t tracked < <(git ls-files -- . "${foreign[@]}")
fi
pinned NODE node "nvm install {}, or another way to put Node {} on PATH" node --version
# A check's key holds the pinned version of the tool it runs.
versions=(
	"--tool=format=${pins[OXFMT]}"
	"--tool=lint=${pins[OXLINT]},${pins[OXLINT_TSGOLINT]},${pins[CLOUDFLARE_OXLINT_CONFIG]}"
	"--tool=types=${pins[TYPESCRIPT]}"
	"--tool=unused=${pins[KNIP]}"
	"--tool=test=${pins[VITEST]},${pins[EFFECT]}"
	"--tool=test-release=${pins[VITEST]},${pins[EFFECT]}"
)
# The project's own vitest, Effect and Stryker run its tests, so each that
# it installs must be at its pin.
installed() {
	local name=$1 package=$2 install=$3
	[ -e "node_modules/$package/package.json" ] || return 0
	pinned "$name" node "$install" \
		node -p "require('./node_modules/$package/package.json').version"
}
if at_least step; then
	installed VITEST vitest "npm install -D vitest@{} @vitest/coverage-v8@{}"
	installed EFFECT effect "npm install effect@{} && npm install -D @effect/vitest@{}"
fi
if full; then
	versions+=("--tool=mutation=${pins[STRYKER]},${pins[VITEST]},${pins[EFFECT]}")
	installed STRYKER @stryker-mutator/core \
		"npm install -D @stryker-mutator/core@{} @stryker-mutator/vitest-runner@{}"
fi
release_versions
units "--toolchain=$(node --version 2>&1)" "${versions[@]}" \
	--project=exceptions,format,lint,types,unused,test,test-release,mutation,duplication,volume

project=$(pwd)
# oxfmt finds a project's own config itself, and is given the standard's
# otherwise. It skips a file of a type it doesn't support.
oxfmt_config=()
if ! existing .oxfmtrc.json .oxfmtrc.jsonc >/dev/null; then
	oxfmt_config=(--config="$(native "$standards/.oxfmtrc.json")")
fi
mapfile -t formatted < <(git ls-files -- . "${foreign[@]}" |
	grep -vE '(^|/)(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?)$')

mapfile -t scripts < <(git ls-files -- '*.ts' '*.tsx' '*.js' '*.mjs' '*.jsx' "${foreign[@]}")

# Oxlint, its type-aware backend and cloudflare's config are installed at
# their pins once, into the cache, and run by oxlint.
oxlint_install() {
	local fresh
	install="$(cache_root)/oxlint/${pins[OXLINT]}-${pins[OXLINT_TSGOLINT]}-${pins[CLOUDFLARE_OXLINT_CONFIG]}"
	[ ! -e "$install/node_modules/oxlint/package.json" ] || return 0
	mkdir -p "${install%/*}"
	fresh=$(mktemp -d "$install.XXXXXX")
	printf '{"private": true, "type": "module"}\n' >"$fresh/package.json"
	npm install --prefix "$(native "$fresh")" --no-audit --no-fund --loglevel=error \
		"oxlint@${pins[OXLINT]}" "oxlint-tsgolint@${pins[OXLINT_TSGOLINT]}" \
		"@cloudflare/oxlint-config@${pins[CLOUDFLARE_OXLINT_CONFIG]}" || return 1
	if [ -e "$install" ]; then rm -rf "$fresh"; else mv "$fresh" "$install"; fi
}

oxlint() {
	node "$(native "$install/node_modules/oxlint/bin/oxlint")" "$@"
}

# The standard's config imports cloudflare's, so it runs from a copy in a run
# folder beside the install, outside node_modules, where Node won't strip
# types, with the standards plugin it loads from beside it. A project's own
# oxlint.config.ts runs from a copy in the run folder's project/, where it
# imports the standard's copy as `#standards/oxlint`, which the run folder's
# package.json maps, and extends it. Sets `run`, the run folder, and
# `oxlint_config`, the config that applies: the project's, or the standard's.
oxlint_run() {
	oxlint_install || return 1
	run=$(mktemp -d "$install/run.XXXXXX")
	printf '{"type": "module", "imports": {"#standards/oxlint": "./oxlint.config.ts"}}\n' \
		>"$run/package.json"
	cp "$standards/oxlint.config.ts" "$run/oxlint.config.ts"
	mkdir "$run/oxlint-plugins"
	cp -r "$standards/oxlint-plugins/index.ts" "$standards/oxlint-plugins/rules" "$run/oxlint-plugins/"
	oxlint_config=$run/oxlint.config.ts
	if [ -z "$own" ] && [ -e oxlint.config.ts ]; then
		mkdir "$run/project"
		cp oxlint.config.ts "$run/project/oxlint.config.ts"
		oxlint_config=$run/project/oxlint.config.ts
	fi
}

oxlint_lint() {
	local install run oxlint_config tsgolint typed= status
	((${#scripts[@]} > 0)) || return 0
	oxlint_run || return 1
	tsgolint=$(cd "$install" && node -p \
		'require.resolve(`@oxlint-tsgolint/${process.platform}-${process.arch}/tsgolint${process.platform === "win32" ? ".exe" : ""}`)') ||
		return 1
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
	# Each package's layer restricts its imports, and the exceptions turn
	# their rules off for their paths, as overrides of a config that extends
	# this one. A package of an unknown layer fails it, naming its manifest.
	mkdir -p node_modules/.cache/standards
	if ! oxlint_config=$(checks oxlint-config "$(native "$oxlint_config")" "${scripts[@]}"); then
		printf '%s\n' "$oxlint_config"
		return 1
	fi
	OXLINT_CONFIG=${typed:+$(native "$typed")} OXLINT_TSGOLINT_PATH=$tsgolint \
		oxlint --config="$(native "$oxlint_config")" "${scripts[@]}"
	status=$?
	rm -rf "$run"
	return "$status"
}

# Drift compares a project's own oxlint.config.ts with the standard's, each
# as Oxlint resolves it, with extends flattened, into the logs.
oxlint_policy() {
	local install run oxlint_config status
	local standard=$logs/oxlint.standard.json own_config=$logs/oxlint.project.json
	if [ -n "$own" ] || [ ! -e oxlint.config.ts ]; then
		policy
		return
	fi
	oxlint_run || return 1
	oxlint --print-config -c "$(native "$run/oxlint.config.ts")" >"$standard" &&
		oxlint --print-config -c "$(native "$oxlint_config")" >"$own_config"
	status=$?
	rm -rf "$run"
	((status == 0)) || return "$status"
	policy "--resolved=oxlint.config.ts=$(native "$own_config")" \
		"--resolved=typescript/oxlint.config.ts=$(native "$standard")"
}

oxfmt_format() {
	((${#formatted[@]} > 0)) || return 0
	npx -y "oxfmt@${pins[OXFMT]}" --check --no-error-on-unmatched-pattern \
		"${oxfmt_config[@]}" "${formatted[@]}"
}

exceptions_unit oxlint_policy
unit format "last 'Format issues found in above [0-9]+ files?|All matched files use the correct format|No files found'" \
	oxfmt_format
unit lint "joined 'Found [0-9]+ (warnings? and [0-9]+ )?(error|warning|info)s?'" \
	oxlint_lint
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
# Vitest runs in the mode of vitest.config.ts that the tier names: fast at
# step, full, with coverage and the slow tests, at release.
if [ -f package.json ] && at_least step; then
	test_check=test
	mode=fast
	if full; then
		test_check=test-release
		mode=full
	fi
	if dry || [ -e node_modules/vitest ]; then
		unit "$test_check" "last 'Tests +[0-9]+ [a-z]+( \| [0-9]+ [a-z]+)*'" \
			npx --no-install vitest run --mode "$mode" --reporter=verbose
	else
		skipped "$test_check" "vitest not installed"
	fi
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
