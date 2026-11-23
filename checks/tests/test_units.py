import json
lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.cargo import workspace
from checks.core.units import (
    Context,
    File,
    digest,
    fingerprint,
    key,
    package_inputs,
    parse_record,
    request,
    run,
)
from checks.core.values import Inputs, Outcome, Request, parse_json

ROOT = "/work"
FILES = FrozenOrderedDict({
    "Cargo.toml": "a1",
    "Cargo.lock": "a2",
    "README.md": "a3",
    "docs/design.md": "a4",
    "tools/scrub.py": "a5",
    "rust-toolchain.toml": "a6",
    "crates/proto/Cargo.toml": "b1",
    "crates/proto/src/lib.rs": "b2",
    "crates/client/Cargo.toml": "c0",
    "crates/client/src/lib.rs": "c1",
    "crates/client/README.md": "c2",
    "crates/client/tests/data.json": "c3",
    "crates/home/Cargo.toml": "d0",
    "crates/home/src/lib.rs": "d1",
    "crates/home/src/flow/test-flow.toml": "d2",
    "crates/app/Cargo.toml": "e0",
    "crates/app/src/main.rs": "e1",
})
SUITES = """
[[suite]]
name = "scrub"
command = "tools/scrub.py --check"
[[suite.when]]
tier = "commit"
paths = ["tools/scrub.py", "docs/**/*.txt"]

[[suite]]
name = "wasm"
command = "tools/wasm.sh"
[[suite.when]]
tier = "commit"
packages = ["client"]

[[suite]]
name = "browser"
command = "tools/e2e.sh"
[[suite.when]]
tier = "step"
paths = ["crates/app/**"]
[[suite.when]]
tier = "release"
"""
PACKAGE_UNITS = FrozenList(
    f"{check} {name}"
    for check in ("lint", "test")
    for name in ("proto", "client", "home", "app")
)


def member(name: str, *dependencies: str) -> Mapping[str, object]:
    return {
        "name": name,
        "manifest_path": f"{ROOT}/crates/{name}/Cargo.toml",
        "dependencies": [
            {"name": "serde", "path": None},
            *(
                {"name": dependency, "path": f"{ROOT}/crates/{dependency}"}
                for dependency in dependencies
            ),
        ],
    }


METADATA = json.dumps({
    "workspace_root": ROOT,
    "packages": [
        member("proto"),
        member("client", "proto"),
        member("home"),
        member("app", "client"),
    ],
})


def listing(files: Mapping[str, str]) -> str:
    return "".join(
        f"100644 {blob:0<40} 0\t{path}\0" for path, blob in files.items()
    )


def outcome(
    files: Mapping[str, str] = FILES,
    *,
    tier: str = "commit",
    suites: str = SUITES,
    **versions: str,
) -> Outcome:
    toolchain = versions.get("toolchain", "cargo 1.95.0-nightly")
    standards = versions.get("standards", "tree")
    lint = versions.get("lint", "clippy 0.1.95")
    texts = FrozenOrderedDict({
        "listing": listing(files),
        "checks.toml": suites,
        "m.json": METADATA,
    })
    arguments = (
        "rust",
        tier,
        "listing",
        "--metadata=m.json",
        f"--standards={standards}",
        f"--toolchain={toolchain}",
        "--project=exceptions,format",
        "--package=lint,test",
        f"--tool=lint={lint}",
        "--tool=test=cargo-nextest 0.9.100",
    )
    return run(arguments, Inputs(texts))


def keyed(
    files: Mapping[str, str] = FILES,
    tier: str = "commit",
    toolchain: str = "cargo 1.95.0-nightly",
) -> FrozenOrderedDict[str, str]:
    result = outcome(files, tier=tier, toolchain=toolchain)
    return FrozenOrderedDict(
        (f"{fields[1]} {fields[2]}", fields[3])
        for line in result.lines
        if (fields := line.split("\t"))[0] == "unit"
    )


def edited(*paths: str) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        (path, "f" if path in paths else blob) for path, blob in FILES.items()
    )


def changed(
    before: Mapping[str, str], after: Mapping[str, str]
) -> FrozenList[str]:
    return FrozenList(unit for unit in before if before[unit] != after[unit])


def rerun(*paths: str, tier: str = "commit") -> FrozenList[str]:
    return changed(keyed(tier=tier), keyed(edited(*paths), tier=tier))


PROJECT_UNITS = ("exceptions .", "format .")


def test_request_reads_the_listing_the_suites_and_the_metadata() -> None:
    arguments = ("rust", "step", "l", "--metadata=m.json")
    assert request(arguments, Inputs()) == (
        Request(FrozenList(("l", "checks.toml", "m.json")))
    )
    assert request(("python", "step", "l"), Inputs()) == Request(
        FrozenList(("l", "checks.toml"))
    )


def test_each_check_is_a_unit_of_the_project_or_of_each_package() -> None:
    assert tuple(keyed()) == (
        "exceptions .",
        "format .",
        *PACKAGE_UNITS,
        "suite scrub",
        "suite wasm",
    )


def test_the_run_lists_packages_and_the_suites_of_its_tier() -> None:
    lines = outcome(tier="step").lines
    assert FrozenList(
        line for line in lines if not line.startswith("unit")
    ) == (
        "package\tproto",
        "package\tclient",
        "package\thome",
        "package\tapp",
        "suite\tscrub\ttools/scrub.py --check",
        "suite\twasm\ttools/wasm.sh",
        "suite\tbrowser\ttools/e2e.sh",
    )
    assert outcome(tier="step").status == 0


def test_unchanged_inputs_give_the_same_distinct_keys() -> None:
    keys = keyed()
    assert keyed() == keys
    assert len(FrozenOrderedSet(keys.values())) == len(keys)
    assert all(len(key) == 40 for key in keys.values())
    assert all(
        character in "0123456789abcdef" for character in keys["lint app"]
    )


def test_changing_a_crate_reruns_it_and_its_dependents() -> None:
    assert rerun("crates/client/src/lib.rs") == (
        "exceptions .",
        "format .",
        "lint client",
        "lint app",
        "test client",
        "test app",
        "suite wasm",
    )
    assert rerun("crates/client/README.md") == rerun("crates/client/src/lib.rs")


def test_changing_a_leaf_crate_reruns_only_it() -> None:
    assert rerun("crates/home/src/lib.rs") == (
        "exceptions .",
        "format .",
        "lint home",
        "test home",
    )


def test_docs_outside_packages_rerun_only_project_units() -> None:
    assert rerun("README.md", "docs/design.md") == ("exceptions .", "format .")


def test_files_outside_every_package_rerun_every_package() -> None:
    assert rerun("rust-toolchain.toml") == (
        *PROJECT_UNITS,
        *PACKAGE_UNITS,
        "suite wasm",
    )
    assert rerun("Cargo.toml") == rerun("rust-toolchain.toml")
    assert rerun("Cargo.lock") == rerun("rust-toolchain.toml")


def test_a_fixture_in_a_crate_reruns_only_that_crate() -> None:
    assert rerun("crates/home/src/flow/test-flow.toml") == (
        *PROJECT_UNITS,
        "lint home",
        "test home",
    )


def test_a_fixture_in_a_dependency_reruns_its_dependents_which_may_read_it() -> (
    None
):
    assert rerun("crates/client/tests/data.json") == rerun(
        "crates/client/src/lib.rs"
    )


def test_a_suite_with_paths_reads_only_those_paths() -> None:
    assert "suite scrub" in rerun("tools/scrub.py")
    assert "suite scrub" not in rerun("Cargo.lock")


def test_a_manifest_reruns_its_crate_and_its_dependents() -> None:
    assert rerun("crates/client/Cargo.toml") == rerun(
        "crates/client/src/lib.rs"
    )


def test_a_suite_follows_its_triggers_at_the_tier() -> None:
    assert "suite browser" in rerun("crates/app/src/main.rs", tier="step")
    assert "suite browser" not in rerun("crates/home/src/lib.rs", tier="step")
    assert "suite browser" in rerun("crates/home/src/lib.rs", tier="release")
    assert "suite browser" in rerun("README.md", tier="release")


def test_the_toolchain_and_the_standards_are_in_every_key() -> None:
    keys = keyed()
    newer = keyed(toolchain="cargo 1.96.0-nightly")
    assert all(keys[unit] != newer[unit] for unit in keys)
    units = FrozenList(
        line for line in outcome().lines if line.startswith("unit")
    )
    changed = outcome(standards="other").lines[: len(units)]
    assert all(a != b for a, b in zip(units, changed, strict=True))


def test_a_key_does_not_depend_on_the_tier() -> None:
    commit, step = keyed(), keyed(tier="step")
    assert all(step[unit] == key for unit, key in commit.items())


def test_suite_problems_are_reported() -> None:
    result = outcome(suites="[other]\n")
    assert result.lines[-1] == "problem\tchecks.toml: unknown table `other`"
    assert result.status == 1


def test_a_project_without_packages_has_only_project_units() -> None:
    texts = FrozenOrderedDict({"l": listing(FILES)})
    arguments = (
        "python",
        "step",
        "l",
        "--standards=s",
        "--toolchain=uv",
        "--project=lint",
        "--package=test",
    )
    (line,) = run(arguments, Inputs(texts)).lines
    assert line.startswith("unit\tlint\t.\t")


def test_keys_hash_the_language_check_scope_and_inputs() -> None:
    context = Context(
        "rust",
        "tree",
        "cargo 1.95.0-nightly",
        FrozenOrderedDict({"lint": "clippy 0.1.95"}),
    )
    files = FrozenList(
        File(path, f"100644 {blob:0<40}") for path, blob in FILES.items()
    )
    whole = fingerprint(files)
    scoped = package_inputs(files, workspace(parse_json(METADATA)))
    keys = keyed()
    assert keys["lint app"] == key(context, "lint", "app", scoped["app"])
    assert keys["exceptions ."] == key(context, "exceptions", ".", whole)
    assert keys["format ."] != key(
        Context("python", "tree", "cargo 1.95.0-nightly"), "format", ".", whole
    )
    assert key(context, "lint", ".", whole) != key(
        context, "lint", "app", whole
    )
    scrub = fingerprint(
        FrozenList(file for file in files if file.path == "tools/scrub.py")
    )
    assert keys["suite scrub"] == key(
        context, "suite tools/scrub.py --check", "scrub", digest((scrub,))
    )
    assert len(FrozenOrderedSet(keys.values())) == len(keys)


def test_a_tool_s_version_may_hold_an_equals_sign() -> None:
    arguments = ("python", "step", "l", "--project=lint", "--tool=lint=a=b")
    (line,) = run(arguments, Inputs()).lines
    expected = key(
        Context("python", "", "", FrozenOrderedDict({"lint": "a=b"})),
        "lint",
        ".",
        fingerprint(()),
    )
    assert line == f"unit\tlint\t.\t{expected}"


def test_a_record_s_path_may_hold_a_tab() -> None:
    assert parse_record("100644 abc 0\ta\tb") == File("a\tb", "100644 abc")


def test_a_tool_s_version_is_in_its_check_s_keys_only() -> None:
    units = FrozenList(
        line for line in outcome().lines if line.startswith("unit")
    )
    newer = outcome(lint="clippy 0.1.96").lines[: len(units)]
    changed = FrozenList(
        " ".join(old.split("\t")[1:3])
        for old, new in zip(units, newer, strict=True)
        if old != new
    )
    assert changed == tuple(unit for unit in PACKAGE_UNITS if "lint" in unit)
