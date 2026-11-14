#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
source "$standards/../lib.sh"
config="$standards/pyproject.toml"
cd "${1:-.}" || exit 2

ruff_config=(--config "$config")
if grep -qs "standards/python/pyproject.toml" pyproject.toml; then
	ruff_config=()
fi
tests="lint.per-file-ignores={'**/tests/**'=['S101'],'**/test_*.py'=['S101']}"
mapfile -t sources < <(git ls-files '*.py' '*.pyw')

step format "last '[0-9]+ files? (would be reformatted|already formatted).*'" \
	uvx -q ruff@latest format "${ruff_config[@]}" --check .
step lint "last 'Found [0-9]+ errors?|All checks passed'" \
	uvx -q ruff@latest check "${ruff_config[@]}" --config "$tests" .
if [ -f uv.lock ]; then
	environment=$(uv run --frozen python -c 'import sys; print(sys.executable)')
	step types "last '[0-9]+ errors?, [0-9]+ warnings?'" \
		uvx -q basedpyright@latest --project "$config" \
		--pythonpath "$environment" "${sources[@]}"
else
	line types skip "no uv.lock"
fi
step unused "count ': unused ' findings" uvx -q vulture "${sources[@]}"
if grep -qs "tool.importlinter" pyproject.toml || [ -f .importlinter ]; then
	step imports "last 'Contracts: .*'" uvx -q --from import-linter lint-imports
fi
step duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
	npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" \
	--format python --silent .
step volume totals scc --include-ext py,pyw --no-cocomo .

finish
