# Sourced from a Rust project root, by check.sh or by a shell before plain
# cargo. A variable the caller already set wins over these.

# The server is started here rather than by the first rustc cargo wraps,
# which can wait on it forever; one already running fails to start, which
# is fine. It outlives a check.sh run, so it starts without lib.sh's run lock.
if [ -z "${RUSTC_WRAPPER:-}" ] && command -v sccache >/dev/null; then
	export RUSTC_WRAPPER=sccache
	(
		[ -z "${run_lock:-}" ] || exec {run_lock}>&-
		sccache --start-server
	) >/dev/null 2>&1 || true
fi
