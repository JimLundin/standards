from ordered import FrozenList, FrozenOrderedDict

from checks.core.attribution import request, run
from checks.core.values import Inputs, Request
from tests.test_units import METADATA

SELECTED = ("proto", "client", "home", "app")
CLIPPY = """\
    Checking proto v0.1.0 (/work/crates/proto)
\x1b[1m\x1b[91merror\x1b[0m: could not compile `proto` (lib) due to 1 previous error
"""
NEXTEST = """\
        PASS [   0.004s] (1/3) proto tests::round_trip
        FAIL [   0.010s] (2/3) client::wire tests::encodes
     TIMEOUT [  60.001s] home tests::waits
     Summary [   1.000s] 3 tests run: 1 passed, 2 failed, 0 skipped
"""


def passing(status: str, log: str, *selected: str) -> FrozenList[str]:
    texts = FrozenOrderedDict({"run.log": log, "m.json": METADATA})
    arguments = (status, "run.log", "m.json", *selected)
    return run(arguments, Inputs(texts)).lines


def test_request_reads_the_log_and_the_metadata() -> None:
    assert request(("1", "run.log", "m.json", "a"), Inputs()) == Request(
        FrozenList(("run.log", "m.json"))
    )


def test_a_passing_run_passes_every_selected_package() -> None:
    assert passing("0", "", *SELECTED) == SELECTED


def test_a_package_that_does_not_compile_fails_with_its_dependents() -> None:
    assert passing("1", CLIPPY, *SELECTED) == ("home",)


def test_failing_tests_fail_only_their_package() -> None:
    assert passing("1", NEXTEST, *SELECTED) == ("proto", "app")


def test_a_failure_no_package_is_named_in_fails_them_all() -> None:
    assert passing("1", "error: linker not found\n", *SELECTED) == ()
    other = "error: could not compile `libc` (lib)\n"
    assert passing("1", other, *SELECTED) == ()


def test_only_selected_packages_pass() -> None:
    assert passing("1", CLIPPY, "home", "app") == ("home",)
    assert passing("1", CLIPPY, "app") == ()
