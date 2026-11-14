#!/usr/bin/env bash
set -uo pipefail

standards=$(cd "$(dirname "$0")" && pwd)
config="$standards/pyproject.toml"
cd "${1:-.}" || exit 2
failed=()

step() {
	local name=$1
	shift
	if ! command -v "$1" >/dev/null; then
		echo "== $name: skipped, $1 not installed"
		return
	fi
	echo "== $name"
	"$@" || failed+=("$name")
}

native() {
	if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi
}

ruff_config=(--config "$config")
if grep -qs "standards/python/pyproject.toml" pyproject.toml; then
	ruff_config=()
fi
tests="lint.per-file-ignores={'**/tests/**'=['S101'],'**/test_*.py'=['S101']}"

python_venv=.venv/Scripts/python.exe
[ -x "$python_venv" ] || python_venv=.venv/bin/python
pyright_env=()
[ -x "$python_venv" ] && pyright_env=(--pythonpath "$python_venv")

mapfile -t sources < <(git ls-files '*.py' '*.pyw')

step format uvx -q ruff@latest format "${ruff_config[@]}" --check .
step lint uvx -q ruff@latest check "${ruff_config[@]}" --config "$tests" .
step types uvx -q basedpyright@latest --project "$config" "${pyright_env[@]}" "${sources[@]}"
step unused uvx -q vulture "${sources[@]}"
if grep -qs "tool.importlinter" pyproject.toml || [ -f .importlinter ]; then
	step imports uvx -q --from import-linter lint-imports
fi
step duplication npx -y jscpd@latest --config "$(native "$standards/../jscpd.json")" --format python --silent .
step volume scc --include-ext py,pyw --no-cocomo .

if ((${#failed[@]})); then
	echo "== failed: ${failed[*]}"
	exit 1
fi
