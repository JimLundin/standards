import json
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict

from checks.core.exceptions import request, run
from checks.core.values import Inputs, Outcome, Request

STD = "C:/standards"


def entry(path: str, rule: str, reason: str = "r") -> str:
    return f'[[exception]]\npath = "{path}"\nrule = "{rule}"\nreason = "{reason}"\n'


def inputs(texts: Mapping[str, str], stdin: str = "", cwd: str = "") -> Inputs:
    return Inputs(FrozenOrderedDict(texts), stdin, cwd)


def lines(outcome: Outcome) -> FrozenList[str]:
    return outcome.lines


def test_request_for_check_lists_project_then_standard_files() -> None:
    files = ("src/a.py", "README.md", "tests/conftest.py")
    assert request(("check", "python", STD, *files), Inputs()) == Request(
        FrozenList((
            "exceptions.toml",
            "pyproject.toml",
            "src/a.py",
            "tests/conftest.py",
            f"{STD}/python/pyproject.toml",
            f"{STD}/python/conftest.py",
        ))
    )


def test_request_for_other_commands() -> None:
    assert request(("globs", "mutation"), Inputs()) == Request(
        FrozenList(("exceptions.toml",))
    )
    for command in ("core-libraries", "stryker-mutate", "biome-plugins"):
        assert request((command, "x.json"), Inputs()) == Request(
            FrozenList(("exceptions.toml", "x.json"))
        )
    assert request(("filter-mutmut",), Inputs()) == Request(
        FrozenList(("exceptions.toml",)), stdin=True
    )


def test_check_passes_a_clean_project() -> None:
    outcome = run(("check", "python", STD, "a.py"), inputs({"a.py": "x = 1\n"}))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)


def test_check_reports_problems_waivers_suppressions_and_drift_in_order() -> (
    None
):
    texts = {
        "exceptions.toml": entry("src/**", "E501")
        + entry("gone/**", "F401")
        + entry("src/a.py", "PUR001:x")
        + entry("pyproject.toml", "drift:tool.pytest.addopts:--b")
        + "[[exception]]\npath = 'x'\n",
        "pyproject.toml": "",
        "src/a.py": "x = 1  # noqa\n",
        f"{STD}/python/pyproject.toml": '[tool.pytest]\naddopts = ["--a", "--b"]\n',
    }
    outcome = run(
        ("check", "python", STD, "src/a.py", "pyproject.toml"), inputs(texts)
    )
    assert lines(outcome) == (
        "exceptions.toml: exception 5 needs a path, a rule and a reason",
        "exceptions.toml (gone/**, F401): path matches no tracked file",
        "src/a.py:1: suppression `# noqa`; add an entry to exceptions.toml instead",
        "pyproject.toml: tool.pytest.addopts lacks `--a` (exception rule `drift:tool.pytest.addopts:--a`)",
        "Found 4 issues",
    )
    assert outcome.status == 1


def test_check_validates_rust_waivers() -> None:
    texts = {
        "exceptions.toml": entry("src/lib.rs", "Bad-Rule")
        + entry("src/lib.rs", "Worse-Rule")
        + entry("src/lib.rs", "clippy::a")
        + entry("gone/**", "dead_code")
        + entry("src/lib.rs", "std")
        + entry("Cargo.toml", "std")
        + entry("profiles/**", "drift:lints.rust.x")
        + entry("src/lib.rs", "clippy::b"),
        "Cargo.toml": "",
        "src/lib.rs": '#[expect(clippy::a, reason = "x")]\nfn f() {}\n',
    }
    outcome = run(
        ("check", "rust", STD, "Cargo.toml", "src/lib.rs"), inputs(texts)
    )
    assert lines(outcome) == (
        "exceptions.toml (src/lib.rs, Bad-Rule): unknown rule for rust",
        "exceptions.toml (src/lib.rs, Worse-Rule): unknown rule for rust",
        "exceptions.toml (gone/**, dead_code): path matches no tracked file",
        "exceptions.toml (src/lib.rs, std): path matches no Cargo.toml",
        "exceptions.toml (src/lib.rs, clippy::b): no matching #[expect] attribute; remove the entry",
        "Found 5 issues",
    )


def test_check_ignores_attributes_outside_rust() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/style/noVar"),
        "a.ts": '#[expect(clippy::a, reason = "x")]\n',
    }
    outcome = run(("check", "typescript", STD, "a.ts"), inputs(texts))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)


def test_ruff_config_groups_rules_by_path() -> None:
    texts = {
        "exceptions.toml": entry("a.py", "E501")
        + entry("b.py", "F401")
        + entry("a.py", "T201")
        + entry("a.py", "IMM001")
        + entry("a.py", "unused")
    }
    assert lines(run(("ruff-config",), inputs(texts))) == (
        'lint.extend-per-file-ignores = {"a.py" = ["E501", "T201"], "b.py" = ["F401"]}',
    )
    assert lines(run(("ruff-config",), inputs({}))) == ()


def test_immutability_and_purity_args() -> None:
    texts = {
        "exceptions.toml": entry("a.py", "IMM001")
        + entry("b/**", "PUR001:attrs")
        + entry("c.py", "E501")
    }
    assert lines(run(("immutability-args",), inputs(texts))) == (
        "--skip=IMM001:a.py",
    )
    assert lines(run(("purity-args",), inputs(texts))) == (
        '--skips=[["PUR001:attrs", "b/**"]]',
    )
    assert lines(run(("purity-args",), inputs({}))) == ()


def test_without_and_globs() -> None:
    texts = {
        "exceptions.toml": entry("a/**", "unused") + entry("b.py", "mutation")
    }
    assert lines(
        run(("without", "unused", "a/x.py", "b.py"), inputs(texts))
    ) == ("b.py",)
    assert lines(run(("globs", "mutation"), inputs(texts))) == ("b.py",)
    assert lines(run(("globs", "api"), inputs(texts))) == ()


def test_biome_groups_by_shared_skips() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/style/noVar")
        + entry("*.ts", "lint/style/useConst")
        + entry("*.ts", "lint/plugin/a")
        + entry("c.js", "mutation")
    }
    outcome = run(
        ("biome-groups", "a.ts", "b.ts", "c.js", "d.ts"), inputs(texts)
    )
    assert lines(outcome) == (
        "style/noVar style/useConst|a.ts",
        "style/useConst|b.ts|d.ts",
        "|c.js",
    )


def test_biome_plugins_resolve_against_the_config() -> None:
    config = json.dumps({"plugins": ["./p/a.grit", {"path": "../b.grit"}, {}]})
    outcome = run(
        ("biome-plugins", "conf/biome.json"),
        inputs({"conf/biome.json": config}, cwd="C:\\work"),
    )
    assert lines(outcome) == (
        "a|C:/work/conf/p/a.grit",
        "b|C:/work/b.grit",
        "|C:/work/conf",
    )
    absolute = run(
        ("biome-plugins", "/std/biome.json"),
        inputs({"/std/biome.json": config}, cwd="/home"),
    )
    assert lines(absolute)[0] == "a|/std/p/a.grit"


def test_filter_mutmut_drops_waived_modules() -> None:
    texts = {
        "exceptions.toml": entry("src/app/shell.py", "mutation")
        + entry("app/cli/__init__.py", "mutation")
    }
    stdin = (
        "    app.shell.x__mutmut_1: survived\n"
        "app.cli.y__mutmut_2: survived\n"
        "app.core.z__mutmut_3: survived\n"
    )
    outcome = run(("filter-mutmut",), inputs(texts, stdin=stdin))
    assert lines(outcome) == ("app.core.z__mutmut_3: survived",)


def test_stryker_mutate_adds_waived_globs() -> None:
    texts = {
        "exceptions.toml": entry("src/skip.ts", "mutation"),
        "stryker.json": json.dumps({"mutate": ["src/**", 3]}),
    }
    assert lines(run(("stryker-mutate", "stryker.json"), inputs(texts))) == (
        "src/**,!src/skip.ts",
    )


def metadata(*packages: tuple[str, str, Sequence[str]]) -> str:
    return json.dumps({
        "workspace_root": "C:\\work",
        "packages": [
            {
                "name": name,
                "manifest_path": f"C:\\work\\{manifest}",
                "targets": [{"kind": list(kinds)}],
            }
            for name, manifest, kinds in packages
        ],
    })


def test_core_libraries_list_checked_libraries() -> None:
    texts = {
        "exceptions.toml": entry("io/Cargo.toml", "std"),
        "m.json": metadata(
            ("core", "core\\Cargo.toml", ("lib",)),
            ("io", "io\\Cargo.toml", ("rlib",)),
            ("macros", "macros\\Cargo.toml", ("proc-macro",)),
            ("app", "app\\Cargo.toml", ("bin",)),
        ),
    }
    assert run(("core-libraries", "m.json"), inputs(texts)) == Outcome(
        FrozenList(("core",))
    )


def test_core_libraries_need_a_library_when_there_are_binaries() -> None:
    texts = {"m.json": metadata(("app", "Cargo.toml", ("bin",)))}
    assert run(("core-libraries", "m.json"), inputs(texts)) == Outcome(
        FrozenList((
            "Cargo.toml: has binaries but no no_std library to hold the pure core",
        )),
        1,
    )
    waived = texts | {"exceptions.toml": entry("Cargo.toml", "std")}
    assert run(("core-libraries", "m.json"), inputs(waived)) == Outcome()
    library_only = {"m.json": metadata(("lib", "Cargo.toml", ("lib",)))}
    assert lines(run(("core-libraries", "m.json"), inputs(library_only))) == (
        "lib",
    )
