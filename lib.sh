logs=$(mktemp -d)
home=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=()
tier=step
project=.
base_ref=
everything=
whole=
lookup=1
mode=all
packages=()
suite_names=()
suite_commands=()

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
# its retry; nextest marks each such test FLAKY.
step() {
	local name=$1 summary=$2
	shift 2
	if ! command -v "$1" >/dev/null; then
		line "$name" skip "$1 not installed"
		return
	fi
	local log="$logs/$name.log" status=ok
	"$@" >"$log" 2>&1 || {
		status=FAIL
		failed+=("$name")
	}
	if [ "$status" = ok ] && plain "$log" | grep -qE '^ *FLAKY '; then
		status=flaky
	fi
	line "$name" "$status" "$(eval "$summary \"\$log\"")"
}

checks() {
	UV_PROJECT_ENVIRONMENT=$(native "$home/checks/.venv-$(uname -s | cut -d_ -f1)") \
		uv run --frozen -q --project "$(native "$home/checks")" python -I -m checks "$@"
}

exceptions() {
	checks exceptions "$@"
}

arguments() {
	while (($# > 0)); do
		case $1 in
		commit | step | release) tier=$1 ;;
		fast) tier=step ;;
		full) tier=release ;;
		--base)
			base_ref=${2:?--base needs a ref}
			shift
			;;
		--base=*) base_ref=${1#--base=} ;;
		--all) everything=--all ;;
		--no-cache) lookup= ;;
		-*)
			echo "unknown option $1; use [commit|step|release] [--base <ref>|--all] [--no-cache] [project]" >&2
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

builds() {
	[ "$mode" != docs ] && [ "$mode" != none ]
}

unbuilt() {
	line "$1" skip "$([ "$mode" = docs ] && echo "docs only" || echo "no changes")"
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

# The git tree of a directory's tracked files and untracked files that are
# not ignored, as they are on disk. It is staged into a copy of the index, so
# the real index is untouched.
tree_of() {
	local index prefix
	index=$(mktemp "$logs/index.XXXXXX")
	prefix=$(git -C "$1" rev-parse --show-prefix 2>/dev/null) || return
	cp "$(git -C "$1" rev-parse --path-format=absolute --git-path index)" "$index" 2>/dev/null || rm -f "$index"
	GIT_INDEX_FILE=$(native "$index") git -C "$1" add -A -- . >/dev/null 2>&1 &&
		GIT_INDEX_FILE=$(native "$index") git -C "$1" write-tree ${prefix:+"--prefix=$prefix"}
}

resolve_base() {
	local ref
	if [ -n "$base_ref" ]; then
		base=$(git rev-parse -q --verify "$base_ref^{commit}") || {
			echo "--base $base_ref is not a commit" >&2
			exit 2
		}
		against="against $base_ref"
		return
	fi
	for ref in "$(git symbolic-ref -q --short refs/remotes/origin/HEAD)" origin/main origin/master main master; do
		[ -n "$ref" ] && git rev-parse -q --verify "$ref^{commit}" >/dev/null || continue
		base=$(git merge-base HEAD "$ref") || continue
		against="against $(git rev-parse --short "$base") (merge base with $ref)"
		return
	done
	return 1
}

# Changed files: what differs between the base and the working tree, plus
# untracked files that are not ignored, relative to the project.
changes() {
	: >"$logs/changed.txt"
	[ -z "$everything" ] || return 0
	{
		git diff --name-only --no-renames --relative -z "$base" -- .
		git ls-files --others --exclude-standard -z -- .
	} | tr '\0' '\n' | sort -u >"$logs/changed.txt"
}

# A pass is recorded under the tier, the base, the standards' tree and the
# project's tree; a pass at a higher tier also counts. Scoping trusts the
# base, so after the standards change each repository first runs whole.
begin() {
	language=$1
	cache=$(cache_root)
	tree=$(tree_of .) || tree=
	standards_tree=$(tree_of "$home") || standards_tree=
	against=
	if [ -n "$everything" ]; then
		base=all
	elif ! resolve_base; then
		base=none
		everything="no base to compare against"
	fi
	pass_keys=()
	seen_keys=()
	if [ -n "$tree" ] && [ -n "$standards_tree" ]; then
		local kind key repository
		repository="$(git rev-parse --path-format=absolute --git-common-dir)/$(git rev-parse --show-prefix)"
		while read -r kind key; do
			case $kind in
			pass) pass_keys+=("$key") ;;
			seen) seen_keys+=("$key") ;;
			esac
		done < <(checks cache-keys "$tier" "$language" "$base" "$standards_tree" "$tree" "$repository")
	fi
	if [ -n "$lookup" ]; then
		for key in "${pass_keys[@]}"; do
			if [ -f "$cache/passed/$key" ]; then
				cat "$cache/passed/$key"
				line cached ok "$tier passed on this tree $(date -r "$cache/passed/$key" '+%F %T'); --no-cache reruns"
				exit 0
			fi
		done
	fi
	if ((${#seen_keys[@]} == 0)); then
		whole="the standards' or project's tree is unknown"
	elif [ ! -f "$cache/seen/${seen_keys[0]}" ]; then
		whole="first whole $tier run with these standards"
	fi
	changes
}

# Scope prints tab-separated records: the mode, a summary, the packages to
# build, the project's suites to run and problems in checks.toml.
scope() {
	local output kind first rest
	output=$(checks scope "$language" "$tier" "$(native "$logs/changed.txt")" \
		${everything:+"--all=$everything"} ${whole:+"--whole=$whole"} "$@")
	while IFS=$'\t' read -r kind first rest; do
		case $kind in
		mode) mode=$first ;;
		summary) line scope - "$tier: $first${against:+, $against}" ;;
		package) packages+=("$first") ;;
		suite)
			suite_names+=("$first")
			suite_commands+=("$rest")
			;;
		problem)
			line suites FAIL "$first"
			failed+=(suites)
			;;
		esac
	done <<<"$output"
	if [ -z "$output" ]; then
		line scope FAIL "the scope check failed"
		failed+=(scope)
		mode=all
	fi
}

suites() {
	local index program words
	for index in "${!suite_names[@]}"; do
		read -r -a words <<<"${suite_commands[index]}"
		for program in "${words[@]}"; do
			[[ $program == *=* ]] || break
		done
		if command -v "$program" >/dev/null; then
			step "${suite_names[index]}" ending bash -c "${suite_commands[index]}"
		else
			line "${suite_names[index]}" skip "$program not installed"
		fi
	done
}

remember() {
	local key
	[ "$(tree_of .)" = "$tree" ] && [ "$(tree_of "$home")" = "$standards_tree" ] || return 0
	mkdir -p "$cache/passed" "$cache/seen"
	cp "$logs/summary.txt" "$cache/passed/${pass_keys[0]}"
	if [ "$mode" = all ] || [ "$mode" = whole ]; then
		for key in "${seen_keys[@]}"; do
			: >"$cache/seen/$key"
		done
	fi
	find "$cache/passed" -type f -mtime +30 -delete 2>/dev/null
	return 0
}

finish() {
	suites
	echo "tier: $tier, logs: $(native "$logs")"
	((${#failed[@]} == 0)) || return 1
	((${#pass_keys[@]} == 0)) || remember
}
