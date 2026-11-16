logs=$(mktemp -d)
failed=()
profile=fast

native() {
	if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi
}

line() {
	printf '%-20s %-5s %s\n' "$1" "$2" "$3"
}

plain() {
	sed 's/\x1b\[[0-9;]*m//g' "$1"
}

last() {
	plain "$2" | grep -oE "$1" | tail -1
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
	line "$name" "$status" "$(eval "$summary \"\$log\"")"
}

pyrun() {
	if command -v uv >/dev/null; then
		uv run --no-project -q --python 3.15 python -I "$@"
	else
		python3 -I "$@"
	fi
}

exceptions() {
	pyrun "$(native "$standards/../exceptions.py")" "$@"
}

full() {
	[ "$profile" = full ]
}

finish() {
	echo "profile: $profile, logs: $(native "$logs")"
	((${#failed[@]} == 0))
}
