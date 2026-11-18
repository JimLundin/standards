import json
lazy from collections.abc import Mapping, Sequence

import pytest
from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.scope import (
    Forced,
    Package,
    Scope,
    dependents,
    owner,
    request,
    run,
    scope,
    summary,
    workspace,
)
from checks.core.values import Inputs, Request, parse_json

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
UNFORCED = Forced()


def scoped(*changed: str, forced: Forced = UNFORCED) -> Scope:
    return scope("rust", FrozenList(changed), PACKAGES, forced)


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


def test_a_changed_package_takes_its_reverse_dependencies() -> None:
    assert scoped("crates/home/src/lib.rs") == Scope(
        "packages", packages=FrozenList(("home", "daemon", "conductord"))
    )
    assert scoped(
        "crates/client/tests/it.rs", "crates/proto/README.md"
    ) == Scope(
        "packages", packages=FrozenList(package.name for package in PACKAGES)
    )


@pytest.mark.parametrize(
    "changed",
    [
        "Cargo.lock",
        "Cargo.toml",
        "crates/home/Cargo.toml",
        "rust-toolchain.toml",
        "clippy.toml",
        "rustfmt.toml",
        ".cargo/config.toml",
        ".config/nextest.toml",
        "exceptions.toml",
        "checks.toml",
    ],
)
def test_project_wide_files_run_everything(changed: str) -> None:
    result = scoped("crates/home/src/lib.rs", changed)
    assert result.mode == "all"
    assert result.reason == f"{changed} changed"
    assert len(result.packages) == len(PACKAGES)


@pytest.mark.parametrize(
    "changed",
    [
        "fixtures/e2e/turn.jsonl",
        "tools/check.sh",
        "crates/claude-cli/tests/fake-claude.sh",
        "crates/home/data.json",
    ],
)
def test_files_outside_rust_sources_run_the_whole_workspace(
    changed: str,
) -> None:
    assert scoped("docs/a.md", changed) == Scope(
        "whole",
        f"{changed} changed",
        FrozenList(package.name for package in PACKAGES),
    )


def test_docs_and_nothing_skip_the_build() -> None:
    assert scoped(
        "README.md", "docs/p1/run.txt", "LICENSE-MIT", ".github/x.yml"
    ) == (Scope("docs"))
    assert scoped() == Scope("none")


def test_forced_scopes_win_in_order() -> None:
    everything = FrozenList(package.name for package in PACKAGES)
    assert scoped(forced=Forced(everything="--all")) == Scope(
        "all", "--all", everything
    )
    assert (
        scoped("Cargo.lock", forced=Forced(whole="new standards")).mode == "all"
    )
    assert scoped("docs/a.md", forced=Forced(whole="new standards")) == Scope(
        "whole", "new standards", everything
    )


def test_python_and_typescript_scope_the_whole_project() -> None:
    assert scope("python", FrozenList(("src/a.py",)), (), Forced()) == Scope(
        "whole", "src/a.py changed"
    )
    assert scope("python", FrozenList(("uv.lock",)), (), Forced()).mode == "all"
    assert scope("python", FrozenList(("docs/a.md",)), (), Forced()) == Scope(
        "docs"
    )
    typescript = scope(
        "typescript", FrozenList(("web/tsconfig.app.json",)), (), Forced()
    )
    assert typescript.mode == "all"


def test_summaries() -> None:
    assert summary(Scope("all", "Cargo.lock changed"), 6) == (
        "everything: Cargo.lock changed"
    )
    assert summary(Scope("whole", "x changed"), 6) == "whole project: x changed"
    assert summary(Scope("packages", packages=FrozenList(("a", "b"))), 6) == (
        "2 of 6 packages: a, b"
    )
    assert (
        summary(Scope("docs"), 6) == "docs only: build and test steps skipped"
    )
    assert (
        summary(Scope("none"), 6) == "no changes: build and test steps skipped"
    )


SUITES = """
[[suite]]
name = "browser"
command = "tools/e2e-browser.sh"
[[suite.when]]
tier = "step"
paths = ["crates/app/**"]
[[suite.when]]
tier = "release"

[[suite]]
name = "wasm"
command = "tools/wasm.sh"
[[suite.when]]
tier = "commit"
packages = ["client"]
"""


def outcome(
    changed: Sequence[str],
    *options: str,
    tier: str = "step",
    suites: str = SUITES,
) -> tuple[FrozenList[str], int]:
    texts = FrozenOrderedDict({
        "changed.txt": "".join(f"{line}\n" for line in changed),
        "m.json": METADATA,
        "checks.toml": suites,
    })
    arguments = ("rust", tier, "changed.txt", "--metadata=m.json", *options)
    result = run(arguments, Inputs(texts))
    return result.lines, result.status


def test_request_reads_the_list_the_suites_and_the_metadata() -> None:
    assert request(
        ("rust", "step", "c.txt", "--metadata=m.json"), Inputs()
    ) == (Request(FrozenList(("c.txt", "checks.toml", "m.json"))))
    assert request(("python", "step", "c.txt"), Inputs()) == Request(
        FrozenList(("c.txt", "checks.toml"))
    )


def test_run_lists_mode_packages_and_suites() -> None:
    assert outcome(("crates\\client\\src\\lib.rs",)) == (
        FrozenList((
            "mode\tpackages",
            "summary\t4 of 6 packages: client, daemon, conductord, app",
            "package\tclient",
            "package\tdaemon",
            "package\tconductord",
            "package\tapp",
            "suite\twasm\ttools/wasm.sh",
        )),
        0,
    )


def test_run_without_packages_lists_none() -> None:
    lines, status = outcome(
        ("crates/app/src/main.rs",), "--all=--all", tier="commit"
    )
    assert lines == (
        "mode\tall",
        "summary\teverything: --all",
        "suite\twasm\ttools/wasm.sh",
    )
    assert status == 0
    lines, _ = outcome(("docs/a.md",), "--whole=new standards")
    assert lines == (
        "mode\twhole",
        "summary\twhole project: new standards",
        "suite\twasm\ttools/wasm.sh",
    )


def test_run_reports_suite_problems() -> None:
    lines, status = outcome(("docs/a.md",), suites="[other]\n")
    assert lines[-1] == "problem\tchecks.toml: unknown table `other`"
    assert status == 1


def test_run_without_metadata_scopes_the_whole_project() -> None:
    texts = FrozenOrderedDict({"c.txt": "src/a.py\n\n"})
    result = run(("python", "step", "c.txt"), Inputs(texts))
    assert result.lines == (
        "mode\twhole",
        "summary\twhole project: src/a.py changed",
    )
