import json
lazy from collections.abc import Mapping

import pytest
from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.units import request, run
from checks.core.values import Inputs, Outcome, Request

ROOT = "/work"
FILES = FrozenOrderedDict({
    "Cargo.toml": "a1",
    "Cargo.lock": "a2",
    "README.md": "a3",
    "docs/design.md": "a4",
    "tools/scrub.py": "a5",
    "crates/proto/Cargo.toml": "b1",
    "crates/proto/src/lib.rs": "b2",
    "crates/client/src/lib.rs": "c1",
    "crates/client/README.md": "c2",
    "crates/home/src/lib.rs": "d1",
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
    return FrozenOrderedDict(
        (f"{fields[1]} {fields[2]}", fields[3])
        for line in outcome(files, tier=tier, toolchain=toolchain).lines
        if (fields := line.split("\t"))[0] == "unit"
    )


def edited(*paths: str) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        (path, "f" if path in paths else blob) for path, blob in FILES.items()
    )


def rerun(*paths: str, tier: str = "commit") -> FrozenList[str]:
    before = keyed(tier=tier)
    after = keyed(edited(*paths), tier=tier)
    return FrozenList(unit for unit in before if before[unit] != after[unit])


def test_request_reads_the_listing_the_suites_and_the_metadata() -> None:
    assert request(("rust", "step", "l", "--metadata=m.json"), Inputs()) == (
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


@pytest.mark.parametrize(
    "path", ["Cargo.lock", "Cargo.toml", "crates/proto/Cargo.toml"]
)
def test_files_outside_package_sources_rerun_every_package(path: str) -> None:
    assert rerun(path) == (
        "exceptions .",
        "format .",
        *PACKAGE_UNITS,
        "suite wasm",
    )


def test_a_suite_with_paths_reads_only_those_paths() -> None:
    assert "suite scrub" in rerun("tools/scrub.py")
    assert "suite scrub" not in rerun("Cargo.lock")


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
