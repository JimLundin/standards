home=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=()
tier=commit
project=.
lookup=1
verify=
affected=
outcome=
suffix=
keyed=
wrote=
standards_tree=
unit_arguments=()
members=()
selected=()
tracked=()
suite_names=()
suite_commands=()
declare -A keys=() recorded=() affected_packages=()
# The tool a unit needs to run, where its command is a function of the
# script; any other unit needs its command.
declare -A tools_of=()

native() {
	if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi
}

# Listing the affected packages, which alone go to stdout, the lines go to
# stderr.
line() {
	if [ -n "$affected" ]; then
		printf '%-20s %-5s %s\n' "$1" "$2" "$3" | tee -a "$logs/summary.txt" >&2
	else
		printf '%-20s %-5s %s\n' "$1" "$2" "$3" | tee -a "$logs/summary.txt"
	fi
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

in_ci() {
	[ -n "${CI:-}" ] && [ "$CI" != false ]
}

# A unit that can't run, such as one whose tool isn't installed, is skipped;
# in CI it fails, so CI passes no tree with a unit it didn't run.
skipped() {
	if in_ci; then
		line "$1" FAIL "$2; CI runs every unit"
		failed+=("$1")
	else
		line "$1" skip "$2"
	fi
}

# Whether the run runs nothing: it verifies or lists the affected packages.
dry() {
	[ -n "$verify$affected" ]
}

# Whether the unit named second can run its tool, skipping it if not. A dry
# run runs no tool, so needs none.
needs() {
	if dry || command -v "$1" >/dev/null; then
		return 0
	fi
	skipped "$2" "$1 not installed"
	return 1
}

# A step passes as flaky when a test listed as flaky failed and passed on
# its retry; nextest marks each such test FLAKY. Its result is left in
# `outcome`, and `suffix`, when set, is added to its summary.
step() {
	local name=$1 summary=$2 log
	shift 2
	if ! needs "${tools_of[$name]:-$1}" "$name"; then
		outcome=skip
		return
	fi
	log="$logs/$name.log"
	outcome=ok
	"$@" >"$log" 2>&1 {run_lock}>&- || {
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

# Prints the first of the files that exists.
existing() {
	local file
	for file; do
		if [ -e "$file" ]; then
			echo "$file"
			return 0
		fi
	done
	return 1
}

arguments() {
	while (($# > 0)); do
		case $1 in
		commit | step | release) tier=$1 ;;
		--no-cache) lookup= ;;
		--verify) verify=1 ;;
		--affected) affected=1 ;;
		-*)
			echo "unknown option $1; use [commit|step|release] [--no-cache|--verify|--affected] [project]" >&2
			exit 2
			;;
		*) project=$1 ;;
		esac
		shift
	done
	if [ -n "$verify" ] && [ -z "$lookup" ]; then
		echo "--verify reads the recorded passes, which --no-cache ignores" >&2
		exit 2
	fi
	if [ -n "$verify" ] && [ -n "$affected" ]; then
		echo "--verify and --affected are two dry runs; pick one" >&2
		exit 2
	fi
	if at_least step && ! dry && ! in_ci && [ "${STANDARDS_LOCAL_TIERS:-}" != 1 ]; then
		echo "$tier runs only in CI; fix: set STANDARDS_LOCAL_TIERS=1 on a machine the owner allows" >&2
		exit 2
	fi
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

declare -A pins=()
while IFS='=' read -r name value; do
	[[ $name =~ ^[A-Z_]+$ ]] && pins[$name]=$value
done <"$home/tools.env"
# uv runs every Python of the checks, the standards' and a project's, at the
# pin, whatever python3 is on PATH.
export UV_PYTHON=${pins[PYTHON]}

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

# One run that runs units at a time per user, across every checkout: each
# takes an flock on one file of the cache, open on `run_lock` for the run's
# life, so the kernel frees it when the run exits, killed or not. Until then,
# and in a run without the lock, `run_lock` is open on /dev/null. A process
# that can outlive the run, such as a unit's or the sccache server, starts
# with it closed. The holder writes its pid and project into the file for a
# run that waits on it.
exec {run_lock}>/dev/null

lock() {
	local file
	dry && return 0
	if ! command -v flock >/dev/null; then
		echo "flock not installed, so this run doesn't wait for another; fix: install util-linux" >&2
		return 0
	fi
	file="$(cache_root)/run.lock"
	mkdir -p "${file%/*}"
	exec {run_lock}>&- {run_lock}>>"$file"
	if ! flock -n "$run_lock"; then
		echo "$(holder "$file") holds $(native "$file"); waiting for it to exit (fix: stop that run or let it finish)" >&2
		flock "$run_lock"
	fi
	echo "run of pid $$, project $(native "$PWD")," >"$file"
}

# The run the lock file names, which is unknown until its holder writes it.
holder() {
	local text
	text=$(cat "$1" 2>/dev/null)
	echo "${text:-an unknown run}"
}

begin() {
	language=$1
	logs=$(mktemp -d)
	lock
	pinned UV uv "uv self update {}" uv --version
	pinned PYTHON uv "uv python install {}" uv run --no-project -q python -V
	mapfile -t tracked < <(git ls-files)
	checks notes fetch
	[ -n "$lookup" ] || return 0
	local key
	while read -r key; do
		recorded[$key]=1
	done < <(checks notes lookup)
}

# Keys each unit of the run, a check over a scope: the project (`.`), a
# package, or a suite. `checks units` derives the keys from the project's
# files, the standards' tree, the pins of tools.env and the arguments, such
# as the toolchain, and lists the workspace's packages and the tier's
# suites. Out of git, every unit runs and none is recorded.
units() {
	local kind first second
	unit_arguments=("$@")
	rekey || return
	while IFS=$'\t' read -r kind first second; do
		case $kind in
		package) members+=("$first") ;;
		suite)
			suite_names+=("$first")
			suite_commands+=("$second")
			;;
		problem)
			line suites FAIL "$first"
			failed+=(suites)
			;;
		esac
	done <"$logs/units.txt"
}

# Takes every unit's key afresh from the project as it is now.
rekey() {
	local kind first second key
	keyed=1
	standards_tree=$(tree_of "$home") && listing "$logs/listing" || {
		keyed=
		: >"$logs/listing"
	}
	checks units "$language" "$tier" "$(native "$logs/listing")" \
		"--standards=$standards_tree" "--pins=$(native "$home/tools.env")" \
		"${unit_arguments[@]}" >"$logs/units.txt"
	if [ ! -s "$logs/units.txt" ]; then
		line units FAIL "the units check failed"
		failed+=(units)
		keyed=
		return 1
	fi
	keys=()
	while IFS=$'\t' read -r kind first second key; do
		[ "$kind" != unit ] || keys["$first $second"]=$key
	done <"$logs/units.txt"
}

known() {
	[ -n "$lookup" ] && [ -n "$keyed" ] && [ -n "${recorded[${keys["$1 $2"]:-none}]:-}" ]
}

# Verifying, fails the unit named second for each of the check's scopes,
# which have no recorded pass, naming the key, and is true; it runs nothing.
unproven() {
	local check=$1 name=$2 scope
	shift 2
	[ -n "$verify" ] || return 1
	(($# > 0)) || return 0
	for scope; do
		line "$name" FAIL "no recorded pass of $scope under ${keys["$check $scope"]:-no key}"
	done
	failed+=("$name")
}

# Records passes of a check's scopes under their keys. If the
# project or the standards changed while it ran, the keys are taken afresh,
# and only scopes whose key still matches are recorded.
remember() {
	local check=$1 scope key
	local -a passes=()
	shift
	[ -n "$keyed" ] && (($# > 0)) || return 0
	local -A before=()
	for scope; do
		before[$scope]=${keys["$check $scope"]:-}
	done
	if ! listing "$logs/listing-now" || ! cmp -s "$logs/listing" "$logs/listing-now" ||
		[ "$(tree_of "$home")" != "$standards_tree" ]; then
		rekey
	fi
	for scope; do
		key=${keys["$check $scope"]:-}
		[ -n "$key" ] && [ "$key" = "${before[$scope]}" ] || continue
		passes+=("$key" "$language $check $scope")
	done
	((${#passes[@]} > 0)) || return 0
	while read -r key; do
		recorded[$key]=1
		wrote=1
	done < <(checks notes record "${passes[@]}")
}

# A check of the whole project.
unit() {
	[ -z "$affected" ] || return 0
	if known "$1" .; then
		line "$1" ok "passed (recorded)"
		return
	fi
	unproven "$1" "$1" . && return
	step "$@"
	case $outcome in
	ok | flaky) remember "$1" . ;;
	esac
}

# A check of packages, run once over the workspace by the function named
# third when any package's pass isn't recorded; those packages are in
# `selected`. `checks passed` credits each failure in its log to a package,
# and the unrecorded packages without one are recorded. Listing the
# affected packages, they are noted and nothing runs.
batch() {
	local check=$1 summary=$2 run=$3 scope status=0
	local -a passing
	shift 3
	selected=()
	for scope; do
		known "$check" "$scope" || selected+=("$scope")
	done
	if [ -n "$affected" ]; then
		for scope in "${selected[@]}"; do
			affected_packages[$scope]=1
		done
		return
	fi
	if (($# > 0)) && ((${#selected[@]} == 0)); then
		line "$check" ok "passed (recorded): $# packages"
		return
	fi
	if ((${#selected[@]} < $#)); then
		suffix="unproven ${selected[*]}; $(($# - ${#selected[@]})) passed (recorded)"
	fi
	unproven "$check" "$check" "${selected[@]}" && return
	step "$check" "$summary" "$run"
	case $outcome in
	skip) return ;;
	FAIL) status=1 ;;
	esac
	mapfile -t passing < <(checks passed "$check" "$status" "$(native "$logs/$check.log")" \
		"$(native "$logs/metadata.json")" "--artifacts=$(native "$logs/$check.jsonl")" \
		"${selected[@]}")
	remember "$check" "${passing[@]}"
}

# A suite runs with the pinned Python first on PATH, so its python3 is the
# one its key names.
suites() {
	local index name program words python
	if python=$(readlink -f "$(uv python find --no-project "$UV_PYTHON" 2>/dev/null)") && [ -n "$python" ]; then
		local -x PATH="${python%/*}:$PATH"
	fi
	for index in "${!suite_names[@]}"; do
		name=${suite_names[index]}
		if known suite "$name"; then
			line "$name" ok "passed (recorded)"
			continue
		fi
		unproven suite "$name" "$name" && continue
		read -r -a words <<<"${suite_commands[index]}"
		for program in "${words[@]}"; do
			[[ $program == *=* ]] || break
		done
		needs "$program" "$name" || continue
		step "$name" ending bash -c "${suite_commands[index]}"
		case $outcome in
		ok | flaky) remember suite "$name" ;;
		esac
	done
}

# A release adds a version of scc to the keys of the volume unit and of
# jscpd to the duplication unit's.
release_versions() {
	full || return 0
	pinned SCC scc "go install github.com/boyter/scc/v3@v{}" scc --version
	versions+=("--tool=duplication=${pins[JSCPD]}" "--tool=volume=${pins[SCC]}")
}

exceptions_unit() {
	unit exceptions "last 'Found [0-9]+ issues|All checks passed'" \
		checks policy "$language" "$(native "$home")" "${tracked[@]}"
}

# The duplication and volume units of a release, over jscpd's formats and
# the file extensions of the language.
release_units() {
	unit duplication "last '[0-9]+ exact clones with [^ ]+ duplicated lines'" \
		npx -y "jscpd@${pins[JSCPD]}" --config "$(native "$home/jscpd.json")" \
		--format "$1" --silent .
	unit volume totals scc --exclude-dir .git,mutants,mutants.out,mutants.out.old,.stryker-tmp \
		--include-ext "$2" --no-cocomo .
}

# Prints the packages, in the workspace's order, that a package check of the
# run would check: those without a recorded pass, which a change to one or
# to a dependency of one leaves.
list_affected() {
	local member
	for member in "${members[@]}"; do
		[ -z "${affected_packages[$member]:-}" ] || echo "$member"
	done
	((${#failed[@]} == 0))
}

finish() {
	if [ -n "$affected" ]; then
		list_affected
		return
	fi
	suites
	if [ -n "$wrote" ] && ! checks notes push; then
		line notes - "passes not pushed to origin"
	fi
	echo "tier: $tier, logs: $(native "$logs")"
	((${#failed[@]} == 0))
}
