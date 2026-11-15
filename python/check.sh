#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
config="$standards/pyproject.toml"
cd "${1:-.}" || exit 2

ruff_config=(--config "$config")
if grep -qs '^\[tool\.ruff' pyproject.toml; then
	ruff_config=()
fi
mapfile -t sources < <(git ls-files '*.py' '*.pyw')

step format "last '[0-9]+ files? (would be reformatted|already formatted).*'" \
	uvx -q ruff@latest format "${ruff_config[@]}" --check .
step lint "last 'Found [0-9]+ errors?|All checks passed'" \
	uvx -q ruff@latest check "${ruff_config[@]}" .
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
	step types "last '[0-9]+ errors?, [0-9]+ warnings?'" \
		uvx -q basedpyright@latest --project "$types_config" \
		--pythonpath "$environment" "${sources[@]}"
	step test "summed 'passed|failed|errors?'" \
		uv run --frozen -q python -m pytest -q
else
	line types skip "no uv.lock"
	line test skip "no uv.lock"
fi
step immutability "last 'Found [0-9]+ issues|All checks passed'" \
	uv run --no-project -q --python 3.15 python -I "$(native "$standards/immutability.py")" \
	"${sources[@]}"
step unused "count ': unused ' findings" uvx -q --python 3.15 vulture "${sources[@]}"
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
step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
	npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" \
	--format python --silent .
step volume totals scc --include-ext py,pyw --no-cocomo .

finish
