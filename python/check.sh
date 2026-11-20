#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
config="$standards/pyproject.toml"
arguments "$@"
cd "$project" || exit 2
begin python
scope

ruff_config=(--config "$config")
if grep -qs '^\[tool\.ruff' pyproject.toml; then
	ruff_config=()
fi
mapfile -t sources < <(git ls-files '*.py' '*.pyw')
mapfile -t tracked < <(git ls-files)
ruff_exceptions=$(tool_config ruff-config)
if [ -n "$ruff_exceptions" ]; then
	ruff_config+=(--config "$ruff_exceptions")
fi
mapfile -t purity_skips < <(tool_config purity-args)
mapfile -t unused_sources < <(tool_config without unused "${sources[@]}")

mutants() {
	plain "$1" | tr '\r' '\n' | grep -oE '(🎉|🙁) [0-9]+' | tail -2 |
		sed 's/🎉/killed/; s/🙁/survived/' |
		awk '{ printf "%s%s %s", s, $2, $1; s = ", " }'
}

mutate() {
	uv run --frozen -q mutmut run || return
	local remaining
	remaining=$(uv run --frozen -q mutmut results | tool_config filter-mutmut)
	echo "$remaining"
	[ -z "$remaining" ]
}

step exceptions "last 'Found [0-9]+ issues|All checks passed'" \
	checks policy python "$(native "$standards/..")" "${tracked[@]}"
step format "last '[0-9]+ files? (would be reformatted|already formatted).*'" \
	uvx -q ruff@latest format "${ruff_config[@]}" --check .
step lint "last 'Found [0-9]+ errors?|All checks passed'" \
	uvx -q ruff@latest check "${ruff_config[@]}" .
if [ -f uv.lock ] && ! builds; then
	unbuilt types
	if at_least step; then
		unbuilt test
	fi
elif [ -f uv.lock ]; then
	environment=$(uv run --frozen -q python -c 'import sys; print(sys.executable)')
	types_config=pyproject.toml
	if ! grep -qs '^\[tool\.basedpyright\]' pyproject.toml; then
		# extraPaths makes the project's own package resolve as local code.
		types_config=$(native "$logs")
		uv run --no-project -q python -c 'import json, sys, tomllib
with open(sys.argv[1], "rb") as file:
    config = tomllib.load(file)["tool"]["basedpyright"]
print(json.dumps({**config, "extraPaths": sys.argv[2:]}))' \
			"$(native "$config")" "$(native "$PWD/src")" "$(native "$PWD")" \
			>"$logs/pyrightconfig.json"
	fi
	step types "last '[0-9]+ errors?, [0-9]+ warnings?'" \
		uvx -q basedpyright@latest --project "$types_config" \
		--pythonpath "$environment" "${sources[@]}"
	if full; then
		thorough=(-m "")
		if grep -rqsE --include=conftest.py 'register_profile\(\s*"full"' .; then
			thorough+=(--hypothesis-profile=full)
		fi
		step test "summed 'passed|failed|errors?'" uv run --frozen -q \
			python -m coverage run -m pytest -q "${thorough[@]}"
		step coverage "last '[0-9]+%'" \
			uv run --frozen -q python -m coverage report
	elif at_least step; then
		step test "summed 'passed|failed|errors?'" \
			uv run --frozen -q python -m pytest -q
	fi
else
	line types skip "no uv.lock"
	if at_least step; then
		line test skip "no uv.lock"
	fi
fi
step immutability "last 'Found [0-9]+ issues|All checks passed'" \
	checks immutability "${sources[@]}"
step purity "last 'Found [0-9]+ issues|All checks passed'" \
	checks purity "${purity_skips[@]}" "${sources[@]}"
if ((${#unused_sources[@]} > 0)); then
	step unused "count ': unused ' findings" \
		uvx -q --python 3.15 vulture "${unused_sources[@]}"
fi
if grep -qs "tool.importlinter" pyproject.toml || [ -f .importlinter ]; then
	imports=(uvx -q --from import-linter lint-imports)
	if [ -f uv.lock ]; then
		# Windows application control can block venv entry-point launchers.
		imports=(uv run --frozen -q python -c
			'from importlinter.cli import lint_imports_command
lint_imports_command()')
	fi
	step imports "last 'Contracts: .*|Could not find .*'" "${imports[@]}"
fi
if full; then
	if ! builds; then
		unbuilt mutation
	elif [ ! -f uv.lock ]; then
		line mutation skip "no uv.lock"
	elif ! uv run --frozen -q python -c 'import os; os.fork' 2>/dev/null; then
		line mutation skip "mutmut needs os.fork (Linux, macOS or WSL)"
	else
		step mutation mutants mutate
	fi
	step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" \
		--format python --silent .
	step volume totals scc --exclude-dir .git,mutants,mutants.out,mutants.out.old,.stryker-tmp --include-ext py,pyw --no-cocomo .
fi

finish
