import json

from ordered import FrozenList, FrozenOrderedDict

from checks.core.attribution import request, run
from checks.core.values import Inputs, Request
from tests.test_units import METADATA, ROOT

SELECTED = ("proto", "client", "home", "app")
CLIPPY = """\
    Checking proto v0.1.0 (/work/crates/proto)
\x1b[1m\x1b[91merror\x1b[0m: could not compile `proto` (lib) due to 1 previous error
"""
NEXTEST = """\
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.10s
    Starting 3 tests across 4 binaries
        PASS [   0.004s] (1/3) proto tests::round_trip
        FAIL [   0.010s] (2/3) client::wire tests::encodes
     TIMEOUT [  60.001s] home tests::waits
     Summary [   1.000s] 3 tests run: 1 passed, 2 failed, 0 skipped
error: test run failed
"""


def artifact(name: str) -> str:
    return json.dumps({
        "reason": "compiler-artifact",
        "manifest_path": f"{ROOT}/crates/{name}/Cargo.toml",
        "target": {"kind": ["lib"], "name": name},
        "fresh": True,
    })


def built(*names: str) -> str:
    finished = json.dumps({"reason": "build-finished", "success": False})
    return "".join(f"{line}\n" for line in (*map(artifact, names), finished))


EVERY = built(*SELECTED)


def passing(
    check: str, status: str, log: str, *selected: str, artifacts: str = EVERY
) -> FrozenList[str]:
    texts = FrozenOrderedDict({
        "run.log": log,
        "m.json": METADATA,
        "a.jsonl": artifacts,
    })
    arguments = (check, status, "run.log", "m.json", "--artifacts=a.jsonl")
    return run((*arguments, *selected), Inputs(texts)).lines


def test_request_reads_the_log_the_metadata_and_the_artifacts() -> None:
    assert request(("lint", "1", "run.log", "m.json", "a"), Inputs()) == (
        Request(FrozenList(("run.log", "m.json")))
    )
    arguments = ("core", "1", "run.log", "m.json", "--artifacts=c.jsonl", "a")
    assert request(arguments, Inputs()) == Request(
        FrozenList(("run.log", "m.json", "c.jsonl"))
    )


def test_a_passing_run_passes_every_selected_package() -> None:
    for check in ("lint", "core", "api", "shell", "test", "other"):
        assert passing(check, "0", "", *SELECTED) == SELECTED


def test_a_package_that_does_not_compile_fails_with_its_dependents() -> None:
    assert passing("lint", "1", CLIPPY, *SELECTED) == ("home",)


def test_failing_tests_fail_only_their_package() -> None:
    assert passing("test", "1", NEXTEST, *SELECTED) == ("proto", "app")
    assert passing("test-release", "1", NEXTEST, *SELECTED) == ("proto", "app")


def test_a_failed_test_build_records_no_package_s_test_pass() -> None:
    log = """\
   Compiling client v0.1.0 (/work/crates/client)
error[E0425]: cannot find value `x` in this scope
 --> crates/client/tests/wire.rs:3:5
error: could not compile `client` (test "wire") due to 1 previous error
error: command `cargo test --no-run` exited with code 101
error: building test binaries failed
"""
    assert passing("test", "1", log, *SELECTED) == ()


def test_a_failed_build_script_records_no_package_s_test_pass() -> None:
    log = """\
error: failed to run custom build command for `home v0.1.0 (/work/crates/home)`
error: building test binaries failed
"""
    assert passing("test", "1", log, *SELECTED) == ()


def test_a_test_run_cut_short_records_nothing() -> None:
    started = NEXTEST.split("     Summary", maxsplit=1)[0]
    assert passing("test", "1", started, *SELECTED) == ()


def test_the_cargo_test_fallback_records_nothing_when_it_fails() -> None:
    log = """\
     Running unittests src/lib.rs (target/debug/deps/proto-1)
test tests::round_trip ... ok
     Running unittests src/lib.rs (target/debug/deps/client-2)
test tests::encodes ... FAILED
error: test failed, to rerun pass `-p client --lib`
"""
    assert passing("test", "101", log, *SELECTED) == ()


def test_a_failure_no_package_is_named_in_fails_them_all() -> None:
    assert passing("lint", "1", "error: linker not found\n", *SELECTED) == ()
    other = "error: could not compile `libc` (lib)\n"
    assert passing("lint", "1", other, *SELECTED) == ()


def test_an_unnamed_error_beside_a_named_one_fails_them_all() -> None:
    log = f"{CLIPPY}error: linker `cc` not found\n"
    assert passing("lint", "1", log, *SELECTED) == ()


def test_a_dependency_that_does_not_build_fails_them_all() -> None:
    log = f"{CLIPPY}error: could not compile `serde` (lib)\n"
    assert passing("lint", "1", log, *SELECTED) == ()


def test_a_failed_build_script_fails_its_package_and_its_dependents() -> None:
    log = (
        "error: failed to run custom build command for "
        "`client v0.1.0 (/work/crates/client)`\n"
    )
    artifacts = built("proto", "home")
    assert passing("lint", "1", log, *SELECTED, artifacts=artifacts) == (
        "proto",
        "home",
    )


def test_a_package_cargo_never_reached_is_not_credited() -> None:
    log = "error: x\n --> crates/home/src/lib.rs:1:1\n"
    artifacts = built("proto", "client")
    assert passing("lint", "1", log, *SELECTED, artifacts=artifacts) == (
        "proto",
        "client",
    )
    assert passing("lint", "1", log, *SELECTED, artifacts="") == ()


def test_only_selected_packages_pass() -> None:
    assert passing("lint", "1", CLIPPY, "home", "app") == ("home",)
    assert passing("lint", "1", CLIPPY, "app") == ()


LINT = """\
warning: unused variable: `x`
 --> crates/home/src/lib.rs:3:9
error: this could be a `const fn`
 --> crates/client/src/lib.rs:6:1
  |
6 | pub fn quadruple(value: u32) -> u32 {
error: could not compile `client` (lib) due to 1 previous error
"""


def test_an_error_is_credited_to_the_package_whose_file_it_is_in() -> None:
    assert passing("lint", "1", LINT, *SELECTED) == ("proto", "home")


def test_a_finding_of_an_analysis_that_finished_fails_its_package() -> None:
    log = (
        "crates/home/src/lib.rs:12: uses `alloc::boxed::Box`\nFound 1 issues\n"
    )
    assert passing("core", "1", log, *SELECTED) == ("proto", "client", "app")
    absolute = "/work/crates/home/src/lib.rs:1: x\nFound 1 issues\n"
    assert passing("api", "1", absolute, *SELECTED) == (
        "proto",
        "client",
        "app",
    )
    assert passing("shell", "1", log, *SELECTED) == ("proto", "client", "app")


def test_an_analysis_that_did_not_finish_records_nothing() -> None:
    log = "crates/home/src/lib.rs:12: uses `alloc::boxed::Box`\n"
    assert passing("core", "1", log, *SELECTED) == ()
    traceback = "Traceback (most recent call last):\nKeyError: 'x'\n"
    assert passing("shell", "1", traceback, *SELECTED) == ()


def test_the_core_credits_only_the_libraries_it_built() -> None:
    log = "crates/home/src/lib.rs:12: x\nFound 1 issues\n"
    artifacts = built("proto", "home")
    assert passing("core", "1", log, *SELECTED, artifacts=artifacts) == (
        "proto",
    )


def test_a_library_the_core_did_not_build_fails() -> None:
    log = "error: could not compile `home` (lib)\nno_std: proto client home\n"
    assert passing("core", "1", log, "proto", "home") == ("proto",)


def test_a_finding_outside_every_package_fails_them_all() -> None:
    log = (
        "crates/home/src/lib.rs:12: x\nCargo.toml: something\nFound 2 issues\n"
    )
    assert passing("core", "1", log, *SELECTED) == ()


def test_a_package_that_cannot_be_documented_fails() -> None:
    log = "error: could not document `home`\nAll checks passed\n"
    assert passing("api", "1", log, *SELECTED) == ("proto", "client", "app")


def test_a_coloured_error_location_alone_fails_its_package() -> None:
    log = (
        "\x1b[1m\x1b[91merror\x1b[0m: this could be a `const fn`\n"
        " --> crates/client/src/lib.rs:6:1\n"
    )
    assert passing("lint", "1", log, *SELECTED) == ("proto", "home", "app")


def test_a_check_without_evidence_records_nothing_when_it_fails() -> None:
    log = "error: x\n --> crates/home/src/lib.rs:1:1\n"
    assert passing("other", "1", log, *SELECTED) == ()


def test_a_missing_log_fails_every_package() -> None:
    texts = FrozenOrderedDict({"m.json": METADATA})
    arguments = ("lint", "1", "run.log", "m.json", *SELECTED)
    assert run(arguments, Inputs(texts)).lines == ()


def test_a_dependency_s_artifact_reaches_no_root_package() -> None:
    metadata = json.dumps({
        "workspace_root": ROOT,
        "packages": [
            {"name": "tool", "manifest_path": f"{ROOT}/Cargo.toml"},
            {"name": "lib", "manifest_path": f"{ROOT}/lib/Cargo.toml"},
        ],
    })
    registry = json.dumps({
        "reason": "compiler-artifact",
        "manifest_path": "/home/u/.cargo/registry/src/syn-3.0.10/Cargo.toml",
    })
    lib = json.dumps({
        "reason": "compiler-artifact",
        "manifest_path": f"{ROOT}/lib/Cargo.toml",
    })
    texts = FrozenOrderedDict({
        "run.log": "error: x\n --> lib/src/lib.rs:1:1\n",
        "m.json": metadata,
        "a.jsonl": f"{registry}\n{lib}\n",
    })
    arguments = ("lint", "1", "run.log", "m.json", "--artifacts=a.jsonl")
    assert run((*arguments, "tool", "lib"), Inputs(texts)).lines == ()
