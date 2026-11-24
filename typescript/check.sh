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
# The project's own vitest, @effect/vitest and Stryker run its tests, so
# each that it installs must be at its pin, and so must the Effect beside
# @effect/vitest. An Effect without it is the project's own dependency.
installed() {
	local name=$1 package=$2 install=$3
	[ -e "node_modules/$package/package.json" ] || return 0
	pinned "$name" node "$install" \
		node -p "require('./node_modules/$package/package.json').version"
}
if at_least step; then
	installed VITEST vitest "npm install -D vitest@{} @vitest/coverage-v8@{}"
	if [ -e node_modules/@effect/vitest/package.json ]; then
		installed EFFECT effect "npm install effect@{} && npm install -D @effect/vitest@{}"
		installed EFFECT @effect/vitest "npm install effect@{} && npm install -D @effect/vitest@{}"
	fi
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
# their pins once, into the cache, and run by oxlint. Their own dependencies
# are pinned by oxlint-install/package-lock.json, whose hash names the install,
# and which npm ci refuses if it doesn't match the pins.
oxlint_install() {
	local fresh lock=$standards/oxlint-install/package-lock.json
	install="$(cache_root)/oxlint/${pins[OXLINT]}-${pins[OXLINT_TSGOLINT]}-${pins[CLOUDFLARE_OXLINT_CONFIG]}-$(sha256sum <"$lock" | cut -c1-16)"
	[ ! -e "$install/node_modules/oxlint/package.json" ] || return 0
	mkdir -p "${install%/*}"
	fresh=$(mktemp -d "$install.XXXXXX")
	printf '{"name": "standards-oxlint", "private": true, "type": "module", "dependencies": {"oxlint": "%s", "oxlint-tsgolint": "%s", "@cloudflare/oxlint-config": "%s"}}\n' \
		"${pins[OXLINT]}" "${pins[OXLINT_TSGOLINT]}" "${pins[CLOUDFLARE_OXLINT_CONFIG]}" >"$fresh/package.json"
	cp "$lock" "$fresh/package-lock.json"
	npm ci --prefix "$(native "$fresh")" --no-audit --no-fund --loglevel=error || return 1
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
	local install run oxlint_config tsgolint untyped=() status
	((${#scripts[@]} > 0)) || return 0
	oxlint_run || return 1
	tsgolint=$(cd "$install" && node -p \
		'require.resolve(`@oxlint-tsgolint/${process.platform}-${process.arch}/tsgolint${process.platform === "win32" ? ".exe" : ""}`)') ||
		return 1
	# The exceptions turn their rules off for their paths, as overrides of a
	# config that extends this one. Without a tsconfig.json there are no types
	# to check, as for the types unit, so the type-aware rules are off.
	if [ ! -f tsconfig.json ]; then
		untyped=(--untyped)
	fi
	mkdir -p node_modules/.cache/standards
	oxlint_config=$(checks oxlint-config "${untyped[@]}" "$(native "$oxlint_config")") || return 1
	# Oxlint picks its output format by where it runs, so the unix one,
	# a line per finding, is named for the summary to count.
	OXLINT_TSGOLINT_PATH=$tsgolint oxlint --format=unix --config="$(native "$oxlint_config")" \
		"${scripts[@]}"
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
unit lint "count '\[(Error|Warning)/' problems" \
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
# vitest runs on the project's own config, a vitest.config.* or the
# vite.config.* vitest reads without one, or else on the standard's, copied
# with the setup file it loads from beside itself into
# node_modules/.cache/standards/, where vitest and Effect resolve from the
# project's install. It finds the tests from the project's root, the working
# folder. Sets `vitest_config`, the copy, or empty for the project's own.
standard_vitest() {
	vitest_config=
	! compgen -G 'vitest.config.*' >/dev/null && ! compgen -G 'vite.config.*' >/dev/null ||
		return 0
	vitest_config=node_modules/.cache/standards/vitest.config.ts
	mkdir -p "${vitest_config%/*}" &&
		cp "$standards/vitest.config.ts" "$standards/vitest.setup.ts" "${vitest_config%/*}/"
}

vitest_run() {
	local vitest_config
	standard_vitest || return 1
	npx --no-install vitest run ${vitest_config:+--config="$vitest_config"} "$@"
}

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
			vitest_run --mode "$mode" --reporter=verbose
	else
		skipped "$test_check" "vitest not installed"
	fi
fi
# Stryker's vitest runner is given the standard's vitest config, when that
# applies, through a copy of the JSON Stryker config with `vitest.configFile`
# set, beside the vitest config's copy.
stryker_run() {
	local vitest_config given=$stryker_given
	standard_vitest || return 1
	if [ -n "$vitest_config" ] && [[ $stryker_config == *.json ]]; then
		given=${vitest_config%/*}/stryker.config.json
		node -e '
			const fs = require("fs");
			const [config, vitest, given] = process.argv.slice(1);
			const parsed = JSON.parse(fs.readFileSync(config, "utf8"));
			parsed.vitest = { ...parsed.vitest, configFile: vitest };
			fs.writeFileSync(given, JSON.stringify(parsed, null, 2));
		' "$(native "$stryker_config")" "$vitest_config" "$given" || return 1
	fi
	npx --no-install stryker run ${given:+"$(native "$given")"} "$@"
}

if full; then
	mutation=()
	# Stryker finds a project's own config itself, and is given the
	# standard's otherwise.
	stryker_config=$(compgen -G 'stryker.conf*' | head -1)
	stryker_given=
	if [ -z "$stryker_config" ]; then
		stryker_config=$standards/stryker.config.json
		stryker_given=$stryker_config
	fi
	mutate=$(checks stryker-mutate "$(native "$stryker_config")")
	if [ -n "$mutate" ]; then
		mutation+=(--mutate "$mutate")
	fi
	if dry || [ -e node_modules/@stryker-mutator/core ]; then
		unit mutation "last 'mutation score (of )?[0-9.]+'" \
			stryker_run "${mutation[@]}"
	else
		skipped mutation "@stryker-mutator/core not installed"
	fi
	release_units typescript,javascript,css ts,tsx,js,mjs,jsx,css
fi

finish
