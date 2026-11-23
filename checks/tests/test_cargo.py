import json
lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedSet

from checks.core.cargo import (
    Package,
    dependencies,
    dependents,
    owned,
    owner,
    reach,
    relative,
    workspace,
)
from checks.core.values import parse_json

ROOT = "C:\\work"


def member(
    name: str, *dependencies: str, path: str = ""
) -> Mapping[str, object]:
    folder = path or f"crates\\{name}"
    return {
        "name": name,
        "manifest_path": f"{ROOT}\\{folder}\\Cargo.toml",
        "dependencies": [
            {"name": "serde", "path": None},
            *(
                {"name": dependency, "path": f"{ROOT}\\crates\\{dependency}"}
                for dependency in dependencies
            ),
        ],
    }


METADATA = json.dumps({
    "workspace_root": ROOT,
    "packages": [
        member("proto"),
        member("client", "proto"),
        member("home", "proto"),
        member("daemon", "home", "client"),
        member("conductord", "daemon"),
        member("app", "client"),
    ],
})
PACKAGES = workspace(parse_json(METADATA))


def test_workspace_reads_members_and_their_path_dependencies() -> None:
    assert PACKAGES[:2] == (
        Package("proto", "crates/proto"),
        Package("client", "crates/client", FrozenList(("proto",))),
    )
    assert PACKAGES[3].dependencies == ("home", "client")


def test_a_root_package_and_an_outside_member() -> None:
    metadata = {
        "workspace_root": "/work",
        "packages": [
            {"name": "root", "manifest_path": "/work/Cargo.toml"},
            {"name": "far", "manifest_path": "/elsewhere/far/Cargo.toml"},
        ],
    }
    assert workspace(metadata) == (
        Package("root", ""),
        Package("far", "/elsewhere/far"),
    )
    root, far = workspace(metadata)
    assert owner("src/main.rs", (root, far)) == root
    assert owner("crates/x/src/lib.rs", (root, Package("x", "crates/x"))) == (
        Package("x", "crates/x")
    )
    assert owner("src/main.rs", (far,)) is None


def test_dependents_close_over_reverse_dependencies_in_order() -> None:
    assert dependents(FrozenOrderedSet(("home",)), PACKAGES) == (
        FrozenOrderedSet(("home", "daemon", "conductord"))
    )
    assert dependents(FrozenOrderedSet(("conductord",)), PACKAGES) == (
        FrozenOrderedSet(("conductord",))
    )


def test_dependencies_close_over_dependencies_in_order() -> None:
    assert dependencies(FrozenOrderedSet(("conductord",)), PACKAGES) == (
        FrozenOrderedSet(("conductord", "daemon", "home", "client", "proto"))
    )
    assert dependencies(FrozenOrderedSet(("proto",)), PACKAGES) == (
        FrozenOrderedSet(("proto",))
    )


def test_owned_files_are_every_file_in_a_package_s_folder() -> None:
    assert owned("crates/home/src/lib.rs", PACKAGES) == "home"
    assert owned("crates/home/README.md", PACKAGES) == "home"
    assert owned("crates/home/Cargo.toml", PACKAGES) == "home"
    assert owned("crates/home/src/flow/test-flow.toml", PACKAGES) == "home"
    assert not owned("tools/check.sh", PACKAGES)


def test_reach_follows_edges_and_keeps_names_without_any() -> None:
    edges = {"a": ("b",), "b": ("c", "a")}
    assert reach(FrozenOrderedSet(("a",)), edges) == FrozenOrderedSet((
        "a",
        "b",
        "c",
    ))
    assert reach(FrozenOrderedSet(("x",)), edges) == FrozenOrderedSet(("x",))


def test_relative_is_empty_at_the_root_and_whole_outside_it() -> None:
    assert relative("C:\\work\\src\\lib.rs", "C:\\work") == "src/lib.rs"
    assert not relative("/work/", "/work")
    assert relative("/elsewhere/x.rs", "/work") == "/elsewhere/x.rs"
