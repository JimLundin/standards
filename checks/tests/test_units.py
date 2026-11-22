import json
lazy from collections.abc import Mapping, Sequence

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
ROOT_MANIFEST = """
[workspace]
members = ["crates/*"]

[workspace.dependencies]
serde = "1"
toml = "0.8"

[workspace.lints.clippy]
pedantic = "warn"

[profile.dev]
debug = "line-tables-only"
"""
MANIFESTS = FrozenOrderedDict({
    "Cargo.toml": ROOT_MANIFEST,
    "crates/proto/Cargo.toml": """
[package]
name = "proto"

[dependencies]
serde = { workspace = true }

[lints]
workspace = true
""",
    "crates/client/Cargo.toml": """
[package]
name = "client"

[dependencies]
proto = { path = "../proto" }
serde.workspace = true
""",
    "crates/home/Cargo.toml": """
[package]
name = "home"

[dependencies]
toml.workspace = true
""",
    "crates/app/Cargo.toml": """
[package]
name = "app"

[dependencies]
client = { path = "../client" }
""",
})
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
VERSIONS = FrozenOrderedDict({
    "serde": "1.0.0",
    "toml": "0.8.0",
    "rand": "0.9.0",
    "itoa": "1.0.0",
})
EDGES = FrozenOrderedDict({
    "proto": (("serde", "normal"),),
    "client": (("proto", "normal"), ("serde", "normal")),
    "home": (("toml", "normal"),),
    "app": (("client", "normal"),),
    "toml": (("serde", "normal"),),
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


def identity(name: str) -> str:
    if name in VERSIONS:
        return f"{REGISTRY}#{name}@{VERSIONS[name]}"
    return f"path+file://{ROOT}/crates/{name}#0.1.0"


def resolve(
    versions: Mapping[str, str] = VERSIONS,
    edges: Mapping[str, Sequence[tuple[str, str]]] = EDGES,
) -> str:
    members = ("proto", "client", "home", "app")
    external = FrozenList(
        {
            "id": f"{REGISTRY}#{name}@{version}",
            "name": name,
            "version": version,
            "source": REGISTRY,
        }
        for name, version in versions.items()
    )
    return json.dumps({
        "workspace_root": ROOT,
        "workspace_members": [identity(name) for name in members],
        "packages": [
            *(
                {
                    "id": identity(name),
                    "name": name,
                    "version": "0.1.0",
                    "source": None,
                }
                for name in members
            ),
            *external,
        ],
        "resolve": {
            "nodes": [
                {
                    "id": f"{REGISTRY}#{name}@{version}"
                    if name in versions
                    else identity(name),
                    "deps": [
                        {
                            "name": dependency,
                            "pkg": f"{REGISTRY}#{dependency}@{versions[dependency]}"
                            if dependency in versions
                            else identity(dependency),
                            "dep_kinds": [
                                {
                                    "kind": None if kind == "normal" else kind,
                                    "target": None,
                                }
                            ],
                        }
                        for dependency, kind in edges.get(name, ())
                    ],
                    "features": [],
                }
                for name, version in (
                    *((member, "") for member in members),
                    *versions.items(),
                )
            ]
        },
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
    manifests: Mapping[str, str] = MANIFESTS,
    resolved: str | None = None,
    **versions: str,
) -> Outcome:
    toolchain = versions.get("toolchain", "cargo 1.95.0-nightly")
    standards = versions.get("standards", "tree")
    lint = versions.get("lint", "clippy 0.1.95")
    texts = FrozenOrderedDict({
        "listing": listing(files),
        "checks.toml": suites,
        "m.json": METADATA,
        "r.json": resolve() if resolved is None else resolved,
        **manifests,
    })
    arguments = (
        "rust",
        tier,
        "listing",
        "--metadata=m.json",
        "--resolve=r.json",
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
    manifests: Mapping[str, str] = MANIFESTS,
    resolved: str | None = None,
) -> FrozenOrderedDict[str, str]:
    result = outcome(
        files,
        tier=tier,
        toolchain=toolchain,
        manifests=manifests,
        resolved=resolved,
    )
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


def rewritten(
    path: str, text: str, *, resolved: str | None = None, lockfile: bool = False
) -> FrozenList[str]:
    paths = (path, "Cargo.lock") if lockfile else (path,)
    manifests = MANIFESTS | FrozenOrderedDict({path: text})
    after = keyed(edited(*paths), manifests=manifests, resolved=resolved)
    return changed(keyed(), after)


def relocked(resolved: str) -> FrozenList[str]:
    return changed(keyed(), keyed(edited("Cargo.lock"), resolved=resolved))


PROJECT_UNITS = ("exceptions .", "format .")


def test_request_reads_the_listing_the_suites_and_the_metadata() -> None:
    arguments = ("rust", "step", "l", "--metadata=m.json", "--resolve=r.json")
    assert request(arguments, Inputs()) == (
        Request(FrozenList(("l", "checks.toml", "m.json", "r.json")))
    )
    described = Inputs(FrozenOrderedDict({"m.json": METADATA}))
    assert request(arguments, described).paths[4:] == (
        "Cargo.toml",
        "crates/proto/Cargo.toml",
        "crates/client/Cargo.toml",
        "crates/home/Cargo.toml",
        "crates/app/Cargo.toml",
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
    profile = ROOT_MANIFEST.replace("line-tables-only", "full")
    assert rewritten("Cargo.toml", profile) == rerun("rust-toolchain.toml")


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


def test_adding_a_dev_dependency_reruns_only_its_crate() -> None:
    manifest = MANIFESTS["crates/client/Cargo.toml"]
    resolved = resolve(
        edges=EDGES
        | FrozenOrderedDict({"client": (*EDGES["client"], ("rand", "dev"))})
    )
    assert rewritten(
        "crates/client/Cargo.toml",
        f'{manifest}\n[dev-dependencies]\nrand = "0.9"\n',
        resolved=resolved,
        lockfile=True,
    ) == (*PROJECT_UNITS, "lint client", "test client", "suite wasm")


def test_adding_a_dependency_reruns_its_crate_and_its_dependents() -> None:
    manifest = MANIFESTS["crates/client/Cargo.toml"]
    resolved = resolve(
        edges=EDGES
        | FrozenOrderedDict({"client": (*EDGES["client"], ("rand", "normal"))})
    )
    assert rewritten(
        "crates/client/Cargo.toml",
        manifest.replace("[dependencies]", '[dependencies]\nrand = "0.9"'),
        resolved=resolved,
        lockfile=True,
    ) == (
        *PROJECT_UNITS,
        "lint client",
        "lint app",
        "test client",
        "test app",
        "suite wasm",
    )


def test_a_lockfile_change_reruns_packages_whose_closure_changed() -> None:
    bumped = resolve(VERSIONS | FrozenOrderedDict({"toml": "0.8.1"}))
    assert relocked(bumped) == (*PROJECT_UNITS, "lint home", "test home")
    shared = resolve(VERSIONS | FrozenOrderedDict({"serde": "1.0.1"}))
    assert relocked(shared) == (*PROJECT_UNITS, *PACKAGE_UNITS, "suite wasm")


def test_a_lockfile_change_outside_every_closure_reruns_no_package() -> None:
    assert relocked(resolve()) == PROJECT_UNITS


def test_without_the_resolve_graph_the_lockfile_reruns_every_package() -> None:
    unresolved = keyed(resolved="")
    after = keyed(edited("Cargo.lock"), resolved="")
    assert changed(unresolved, after) == (
        *PROJECT_UNITS,
        *PACKAGE_UNITS,
        "suite wasm",
    )


def test_a_workspace_dependency_reruns_the_packages_that_inherit_it() -> None:
    featured = ROOT_MANIFEST.replace(
        'toml = "0.8"', 'toml = { version = "0.8", features = ["parse"] }'
    )
    assert rewritten("Cargo.toml", featured) == (
        *PROJECT_UNITS,
        "lint home",
        "test home",
    )


def test_workspace_lints_rerun_the_packages_that_take_them() -> None:
    stricter = ROOT_MANIFEST.replace('pedantic = "warn"', 'pedantic = "deny"')
    assert rewritten("Cargo.toml", stricter) == (
        *PROJECT_UNITS,
        "lint proto",
        "test proto",
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
