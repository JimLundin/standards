#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
config="$standards/pyproject.toml"
arguments "$@"
cd "$project" || exit 2
begin python

# A check's key holds the pinned version of the tool it runs.
versions=(
	"--tool=format=${pins[RUFF]}"
	"--tool=lint=${pins[RUFF]}"
	"--tool=types=${pins[BASEDPYRIGHT]}"
	"--tool=unused=${pins[VULTURE]}"
	"--tool=imports=${pins[IMPORT_LINTER]}"
)
release_versions
python=
if [ -f uv.lock ]; then
	python=$(uv run --frozen -q python -V 2>&1)
fi
units "--toolchain=$(uv --version 2>&1) $python" "${versions[@]}" \
	--project=exceptions,format,lint,types,test,test-release,coverage,immutability,purity,unused,imports,mutation,duplication,volume

ruff_config=(--config "$config")
if grep -qs '^\[tool\.ruff' pyproject.toml; then
	ruff_config=()
fi
mapfile -t sources < <(git ls-files '*.py' '*.pyw')
ruff_exceptions=$(checks ruff-config)
if [ -n "$ruff_exceptions" ]; then
	ruff_config+=(--config "$ruff_exceptions")
fi
mapfile -t unused_sources < <(checks without unused "${sources[@]}")

mutants() {
	plain "$1" | tr '\r' '\n' | grep -oE '(🎉|🙁) [0-9]+' | tail -2 |
		sed 's/🎉/killed/; s/🙁/survived/' |
		awk '{ printf "%s%s %s", s, $2, $1; s = ", " }'
}

mutate() {
	uv run --frozen -q mutmut run || return
	local remaining
	remaining=$(uv run --frozen -q mutmut results | checks filter-mutmut)
	echo "$remaining"
	[ -z "$remaining" ]
}

exceptions_unit
unit format "last '[0-9]+ files? (would be reformatted|already formatted).*'" \
	uvx -q "ruff@${pins[RUFF]}" format "${ruff_config[@]}" --check .
unit lint "last 'Found [0-9]+ errors?|All checks passed'" \
	uvx -q "ruff@${pins[RUFF]}" check "${ruff_config[@]}" .
if [ -f uv.lock ]; then
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
	unit types "last '[0-9]+ errors?, [0-9]+ warnings?'" \
		uvx -q "basedpyright@${pins[BASEDPYRIGHT]}" --project "$types_config" \
		--pythonpath "$environment" "${sources[@]}"
	if full; then
		thorough=(-m "")
		if grep -rqsE --include=conftest.py 'register_profile\(\s*"full"' .; then
			thorough+=(--hypothesis-profile=full)
		fi
		unit test-release "summed 'passed|failed|errors?'" uv run --frozen -q \
			python -m coverage run -m pytest -q "${thorough[@]}"
		unit coverage "last '[0-9]+%'" \
			uv run --frozen -q python -m coverage report
	elif at_least step; then
		unit test "summed 'passed|failed|errors?'" \
			uv run --frozen -q python -m pytest -q
	fi
else
	line types skip "no uv.lock"
	if at_least step; then
		line test skip "no uv.lock"
	fi
fi
unit immutability "last 'Found [0-9]+ issues|All checks passed'" \
	checks immutability "${sources[@]}"
unit purity "last 'Found [0-9]+ issues|All checks passed'" \
	checks purity "${sources[@]}"
if ((${#unused_sources[@]} > 0)); then
	unit unused "count ': unused ' findings" \
		uvx -q --python 3.15 "vulture==${pins[VULTURE]}" "${unused_sources[@]}"
fi
if grep -qs "tool.importlinter" pyproject.toml || [ -f .importlinter ]; then
	imports=(uvx -q --from "import-linter==${pins[IMPORT_LINTER]}" lint-imports)
	if [ -f uv.lock ]; then
		# Windows application control can block venv entry-point launchers.
		imports=(uv run --frozen -q python -c
			'from importlinter.cli import lint_imports_command
lint_imports_command()')
	fi
	unit imports "last 'Contracts: .*|Could not find .*'" "${imports[@]}"
fi
if full; then
	if [ ! -f uv.lock ]; then
		line mutation skip "no uv.lock"
	elif [ -z "$verify" ] && ! uv run --frozen -q python -c 'import os; os.fork' 2>/dev/null; then
		skipped mutation "mutmut needs os.fork (Linux, macOS or WSL)"
	else
		unit mutation mutants mutate
	fi
	release_units python py,pyw
fi

finish
