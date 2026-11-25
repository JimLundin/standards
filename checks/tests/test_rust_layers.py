import json
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList

from checks.core.rust_layers import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import assert_lines_name_the_fix, inputs

CORELESS = (
    "has binaries but no no_std library to hold the pure core; fix: add a"
    " `#![no_std]` library package for the core, or set"
    ' package.metadata.standards.layer = "shell" on this package'
)


def test_request_reads_the_metadata() -> None:
    assert request(("m.json",), Inputs()) == Request(FrozenList(("m.json",)))


def package(
    name: str, kinds: Sequence[str], layer: object = None
) -> Mapping[str, object]:
    return {
        "name": name,
        "id": f"path+file:///C:/work/{name}#0.1.0",
        "manifest_path": f"C:\\work\\{name}\\Cargo.toml",
        "targets": [{"kind": list(kinds)}],
        "metadata": None if layer is None else {"standards": {"layer": layer}},
    }


def metadata(*packages: Mapping[str, object]) -> str:
    return json.dumps({"workspace_root": "C:\\work", "packages": packages})


def core_libraries(*packages: Mapping[str, object]) -> Outcome:
    texts = {"m.json": metadata(*packages)}
    outcome = run(("m.json",), inputs(texts))
    assert_lines_name_the_fix(outcome.lines if outcome.status else ())
    return outcome


def test_undeclared_libraries_are_core() -> None:
    assert core_libraries(
        package("core", ("lib",)),
        package("io", ("rlib",), layer="shell"),
        package("pure", ("rlib",), layer="core"),
        package("macros", ("proc-macro",)),
        package("app", ("bin",)),
        package("cli", ("lib", "bin"), layer="shell"),
    ) == Outcome(FrozenList(("core", "pure")))


def test_core_libraries_report_invalid_layers() -> None:
    assert core_libraries(
        package("a", ("lib",), layer="Shell"),
        package("b", ("lib",), layer=1),
        package("c", ("lib",), layer=["shell"]),
        package("d", ("lib",)),
    ) == Outcome(
        FrozenList((
            'a/Cargo.toml: package.metadata.standards.layer is "Shell"; fix: set package.metadata.standards.layer to "core" or "shell"',
            'b/Cargo.toml: package.metadata.standards.layer is 1; fix: set package.metadata.standards.layer to "core" or "shell"',
            'c/Cargo.toml: package.metadata.standards.layer is ["shell"]; fix: set package.metadata.standards.layer to "core" or "shell"',
        )),
        1,
    )


def test_core_libraries_need_a_library_when_there_are_binaries() -> None:
    assert core_libraries(
        package("app", ("bin",)), package("cli", ("bin",), layer="core")
    ) == Outcome(
        FrozenList((
            f"app/Cargo.toml: {CORELESS}",
            f"cli/Cargo.toml: {CORELESS}",
        )),
        1,
    )
    assert core_libraries(
        package("app", ("bin",)), package("io", ("lib",), layer="shell")
    ) == Outcome(FrozenList((f"app/Cargo.toml: {CORELESS}",)), 1)
    assert core_libraries(package("app", ("bin",), layer="shell")) == Outcome()
    assert (
        core_libraries(package("app", ("lib", "bin"), layer="shell"))
        == Outcome()
    )
    assert core_libraries(
        package("app", ("bin",)), package("core", ("lib",))
    ) == Outcome(FrozenList(("core",)))
