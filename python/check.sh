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
	"--tool=unused-tests=${pins[VULTURE]}"
	"--tool=imports=${pins[IMPORT_LINTER]}"
)
release_versions
# The Python uv resolves for the project, at the pin, as every check runs it.
python=$(uv run --no-project -q python -V 2>&1)
if [ -f uv.lock ]; then
	python=$(uv run --frozen -q python -V 2>&1)
fi
units "--toolchain=$(uv --version 2>&1) $python" "${versions[@]}" \
	--project=exceptions,format,lint,types,test,test-release,immutability,purity,unused,unused-tests,imports,mutation,duplication,volume \
	--side=unused=sources --side=unused-tests=tests

ruff_config=(--config "$config")
if grep -qs '^\[tool\.ruff' pyproject.toml; then
	ruff_config=()
fi
mapfile -t sources < <(git ls-files '*.py' '*.pyw')
source_files=()
test_files=()
if ((${#sources[@]} > 0)); then
	while IFS=$'\t' read -r side file; do
		case $side in
		sources) source_files+=("$file") ;;
		tests) test_files+=("$file") ;;
		esac
	done < <(printf '%s\n' "${sources[@]}" | checks sides)
fi
ruff_exceptions=$(checks ruff-config)
if [ -n "$ruff_exceptions" ]; then
	ruff_config+=(--config "$ruff_exceptions")
fi

mutants() {
	plain "$1" | tr '\r' '\n' | grep -oE '(🎉|🙁) [0-9]+' | tail -2 |
		sed 's/🎉/killed/; s/🙁/survived/' |
		awk '{ printf "%s%s %s", s, $2, $1; s = ", " }'
}

# mutmut keeps a mutant's result while its function is unchanged, even when
# the tests changed, so each run starts without the last one's mutants.
mutate() {
	rm -rf mutants
	uv run --frozen -q mutmut run || return
	local remaining
	remaining=$(uv run --frozen -q mutmut results | checks filter-mutmut)
	echo "$remaining"
	[ -z "$remaining" ]
}

# The release's tests and their coverage are one unit, so the report reads
# only the data of the run before it.
measured() {
	uv run --frozen -q python -m coverage run -m pytest -q "${thorough[@]}" &&
		uv run --frozen -q python -m coverage report
}

# Vulture reads the files of one side, the sources or the tests, so a use in a
# test never keeps a source alive. Within a side, a use in a file excepted
# from `unused` still counts; the findings inside such files are dropped after
# it runs. Vulture exits 3 when it finds unused code, and with another nonzero
# status when it fails.
unused_findings() {
	local findings status
	findings=$(uvx -q --python 3.15 "vulture==${pins[VULTURE]}" "$@" 2>&1)
	status=$?
	if ((status != 0 && status != 3)); then
		echo "$findings"
		return "$status"
	fi
	findings=$(checks filter-vulture <<<"$findings")
	echo "$findings"
	[ -z "$findings" ]
}

covered() {
	echo "$(summed 'passed|failed|errors?' "$1"); coverage $(last '[0-9]+%' "$1")"
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
		tools_of[test-release]=uv
		unit test-release covered measured
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
if ((${#source_files[@]} > 0)); then
	tools_of[unused]=uvx
	unit unused "count ': unused ' findings" unused_findings "${source_files[@]}"
fi
if ((${#test_files[@]} > 0)); then
	tools_of[unused-tests]=uvx
	unit unused-tests "count ': unused ' findings" unused_findings "${test_files[@]}"
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
	elif ! dry && ! uv run --frozen -q python -c 'import os; os.fork' 2>/dev/null; then
		skipped mutation "mutmut needs os.fork" "run it on Linux, macOS or WSL"
	else
		unit mutation mutants mutate
	fi
	release_units python py,pyw
fi

finish
