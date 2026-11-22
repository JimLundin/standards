logs=$(mktemp -d)
home=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=()
tier=step
project=.
lookup=1
outcome=
suffix=
keyed=
wrote=
standards_tree=
unit_arguments=()
members=()
selected=()
suite_names=()
suite_commands=()
declare -A keys=() recorded=()

native() {
	if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi
}

line() {
	printf '%-20s %-5s %s\n' "$1" "$2" "$3" | tee -a "$logs/summary.txt"
}

plain() {
	sed 's/\x1b\[[0-9;]*m//g' "$1"
}

last() {
	plain "$2" | grep -oE "$1" | tail -1
}

ending() {
	plain "$1" | grep . | tail -1
}

count() {
	echo "$(plain "$3" | grep -cE "$1") $2"
}

joined() {
	plain "$2" | grep -oE "$1" | sed 's/^Found //' | paste -sd ',' - | sed 's/,/, /g'
}

summed() {
	plain "$2" | grep -oE "[0-9]+ ($1)" |
		awk '{ n[$2] += $1 } END { for (k in n) { printf "%s%d %s", s, n[k], k; s = ", " } }'
}

totals() {
	plain "$1" | awk '/^Total/ { printf "%s files, %s code, %s comments, %s complexity", $2, $6, $5, $7 }'
}

# A step passes as flaky when a test listed as flaky failed and passed on
# its retry; nextest marks each such test FLAKY. Its result is left in
# `outcome`, and `suffix`, when set, is added to its summary.
step() {
	local name=$1 summary=$2 log
	shift 2
	if ! command -v "$1" >/dev/null; then
		outcome=skip
		line "$name" skip "$1 not installed"
		return
	fi
	log="$logs/$name.log"
	outcome=ok
	"$@" >"$log" 2>&1 || {
		outcome=FAIL
		failed+=("$name")
	}
	if [ "$outcome" = ok ] && plain "$log" | grep -qE '^ *FLAKY '; then
		outcome=flaky
	fi
	line "$name" "$outcome" "$(eval "$summary \"\$log\"")${suffix:+; $suffix}"
	suffix=
}

checks() {
	UV_PROJECT_ENVIRONMENT=$(native "$home/checks/.venv-$(uname -s | cut -d_ -f1)") \
		uv run --frozen -q --project "$(native "$home/checks")" python -I -m checks "$@"
}

tool_config() {
	checks tool-config "$@"
}

arguments() {
	while (($# > 0)); do
		case $1 in
		commit | step | release) tier=$1 ;;
		fast) tier=step ;;
		full) tier=release ;;
		--no-cache) lookup= ;;
		-*)
			echo "unknown option $1; use [commit|step|release] [--no-cache] [project]" >&2
			exit 2
			;;
		*) project=$1 ;;
		esac
		shift
	done
}

at_least() {
	local order=" commit step release "
	local mine=${order%% "$tier" *} wanted=${order%% "$1" *}
	((${#mine} >= ${#wanted}))
}

full() {
	at_least release
}

cache_root() {
	if [ -n "${STANDARDS_CACHE:-}" ]; then
		echo "$STANDARDS_CACHE"
	elif [ -n "${LOCALAPPDATA:-}" ] && command -v cygpath >/dev/null; then
		echo "$(cygpath -u "$LOCALAPPDATA")/standards"
	else
		echo "${XDG_CACHE_HOME:-$HOME/.cache}/standards"
	fi
}

# Runs a git command in a directory against an index of the standards' own,
# holding its tracked files and untracked files that are not ignored, as they
# are on disk, so the real index is untouched. The index is kept in the cache
# so that its stat data stays fresh where another git wrote the real index
# (WSL reading a Windows checkout), and a private copy is used while it is
# busy.
staged() {
	local directory=$1 real kept index
	shift
	real=$(git -C "$directory" rev-parse --path-format=absolute --git-path index 2>/dev/null) || return
	kept="$(cache_root)/index/$(printf '%s' "$real" | sha256sum | cut -c1-32)"
	mkdir -p "${kept%/*}"
	[ -f "$kept" ] || cp "$real" "$kept" 2>/dev/null
	for index in "$kept" "$(mktemp "$logs/index.XXXXXX")"; do
		[ "$index" = "$kept" ] || cp "$real" "$index" 2>/dev/null || rm -f "$index"
		if GIT_INDEX_FILE=$(native "$index") git -C "$directory" add -A -- . >/dev/null 2>&1; then
			GIT_INDEX_FILE=$(native "$index") git -C "$directory" "$@"
			return
		fi
	done
	return 1
}

tree_of() {
	local prefix
	prefix=$(git -C "$1" rev-parse --show-prefix 2>/dev/null) || return
	staged "$1" write-tree ${prefix:+"--prefix=$prefix"}
}

listing() {
	staged . ls-files -s -z -- . >"$1"
}

# Passes are notes on refs/notes/checks, which travel with origin: fetched
# notes are merged by union, and a project without origin keeps them local.
notes() {
	git remote get-url origin >/dev/null 2>&1 || return 0
	case $1 in
	fetch)
		git fetch -q origin "+refs/notes/checks:refs/notes/origin/checks" 2>/dev/null &&
			git notes --ref=checks merge -q -s cat_sort_uniq refs/notes/origin/checks >/dev/null 2>&1
		;;
	push)
		[ -n "$wrote" ] || return 0
		git push -q origin refs/notes/checks 2>/dev/null ||
			{ notes fetch && git push -q origin refs/notes/checks 2>/dev/null; } ||
			line notes - "passes not pushed to origin"
		;;
	esac
	return 0
}

declare -A pins=()
while IFS='=' read -r name value; do
	[[ $name =~ ^[A-Z_]+$ ]] && pins[$name]=$value
done <"$home/tools.env"

# Fails fast when an installed tool isn't at its version in tools.env, naming
# the command that installs it there, with {} for the version. A tool that
# isn't installed is left to its step.
pinned() {
	local name=$1 probe=$2 install=$3 found pin
	shift 3
	command -v "$probe" >/dev/null || return 0
	pin=${pins[$name]}
	found=$("$@" 2>&1 | head -1)
	[[ " $found " =~ [^0-9.]${pin//./\.}[^0-9.] ]] && return 0
	echo "$found is not $name=$pin from $(native "$home/tools.env"); install it with: ${install//\{\}/$pin}" >&2
	exit 2
}

begin() {
	language=$1
	pinned UV uv "uv self update {}" uv --version
	pinned PYTHON python3 "uv python install {}, and put it first on PATH as python3" python3 --version
	notes fetch
	[ -n "$lookup" ] || return 0
	local object
	while read -r _ object; do
		recorded[$object]=1
	done < <(git notes --ref=checks list 2>/dev/null)
}

# Keys each unit of the run, a check over a scope: the project (`.`), a
# package, or a suite. `checks units` derives the keys from the project's
# files, the standards' tree and the arguments, such as the toolchain. Out of
# git, every unit runs and none is recorded.
units() {
	local output kind first second rest first_time=1
	((${#unit_arguments[@]} == 0)) || first_time=
	unit_arguments=("$@")
	keyed=1
	standards_tree=$(tree_of "$home") && listing "$logs/listing" || {
		keyed=
		: >"$logs/listing"
	}
	output=$(checks units "$language" "$tier" "$(native "$logs/listing")" \
		"--standards=$standards_tree" "$@")
	if [ -z "$output" ]; then
		line units FAIL "the units check failed"
		failed+=(units)
		keyed=
		return
	fi
	keys=()
	while IFS=$'\t' read -r kind first second rest; do
		case $kind in
		unit) keys["$first $second"]=$rest ;;
		*) [ -z "$first_time" ] || unlisted "$kind" "$first" "$second" ;;
		esac
	done <<<"$output"
}

unlisted() {
	case $1 in
	package) members+=("$2") ;;
	suite)
		suite_names+=("$2")
		suite_commands+=("$3")
		;;
	problem)
		line suites FAIL "$2"
		failed+=(suites)
		;;
	esac
}

known() {
	[ -n "$lookup" ] && [ -n "$keyed" ] && [ -n "${recorded[${keys["$1 $2"]:-none}]:-}" ]
}

# Records passes of a check's scopes as notes under their keys. If the
# project or the standards changed while it ran, the keys are taken afresh,
# and only scopes whose key still matches are recorded.
remember() {
	local check=$1 scope key
	shift
	[ -n "$keyed" ] && (($# > 0)) || return 0
	local -A before=()
	for scope; do
		before[$scope]=${keys["$check $scope"]:-}
	done
	if ! listing "$logs/listing-now" || ! cmp -s "$logs/listing" "$logs/listing-now" ||
		[ "$(tree_of "$home")" != "$standards_tree" ]; then
		units "${unit_arguments[@]}"
	fi
	for scope; do
		key=${keys["$check $scope"]:-}
		[ -n "$key" ] && [ "$key" = "${before[$scope]}" ] || continue
		git notes --ref=checks add -f -m "$language $check $scope" "$key" >/dev/null 2>&1 || continue
		recorded[$key]=1
		wrote=1
	done
}

# A check of the whole project.
unit() {
	if known "$1" .; then
		line "$1" ok "passed (recorded)"
		return
	fi
	step "$@"
	case $outcome in
	ok | flaky) remember "$1" . ;;
	esac
}

# A check of packages, run once over the workspace by the function named
# third when any package's pass isn't recorded; those packages are in
# `selected`. `checks passed` credits each failure in its log to a package,
# and the unrecorded packages without one are recorded.
batch() {
	local check=$1 summary=$2 run=$3 scope status=0
	local -a passing
	shift 3
	selected=()
	for scope; do
		known "$check" "$scope" || selected+=("$scope")
	done
	if (($# > 0)) && ((${#selected[@]} == 0)); then
		line "$check" ok "passed (recorded): $# packages"
		return
	fi
	if ((${#selected[@]} < $#)); then
		suffix="unproven ${selected[*]}; $(($# - ${#selected[@]})) passed (recorded)"
	fi
	step "$check" "$summary" "$run"
	case $outcome in
	skip) return ;;
	FAIL) status=1 ;;
	esac
	mapfile -t passing < <(checks passed "$status" "$(native "$logs/$check.log")" \
		"$(native "$logs/metadata.json")" "${selected[@]}")
	remember "$check" "${passing[@]}"
}

suites() {
	local index name program words
	for index in "${!suite_names[@]}"; do
		name=${suite_names[index]}
		if known suite "$name"; then
			line "$name" ok "passed (recorded)"
			continue
		fi
		read -r -a words <<<"${suite_commands[index]}"
		for program in "${words[@]}"; do
			[[ $program == *=* ]] || break
		done
		if ! command -v "$program" >/dev/null; then
			line "$name" skip "$program not installed"
			continue
		fi
		step "$name" ending bash -c "${suite_commands[index]}"
		case $outcome in
		ok | flaky) remember suite "$name" ;;
		esac
	done
}

finish() {
	suites
	notes push
	echo "tier: $tier, logs: $(native "$logs")"
	((${#failed[@]} == 0))
}
