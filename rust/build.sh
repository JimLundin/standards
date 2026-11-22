# Sourced from a Rust project root, by check.sh or by a shell before plain
# cargo. A variable the caller already set wins over these.

if [ -z "${RUSTC_WRAPPER:-}" ] && command -v sccache >/dev/null; then
	export RUSTC_WRAPPER=sccache
fi
