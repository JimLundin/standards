import json
lazy from collections.abc import Mapping, Sequence

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import (
    Snapshot,
    biome_levels,
    hypothesis_profiles,
    level,
    proptest_cases,
    python_drift,
    runs,
    rust_drift,
    typescript_drift,
)
from checks.core.values import parse_toml
from checks.core.waivers import Issue


def snapshot(
    project: Mapping[str, str],
    standards: Mapping[str, str],
    files: Sequence[str] = (),
) -> Snapshot:
    return Snapshot(
        FrozenList(files or tuple(project)),
        FrozenOrderedDict(project),
        FrozenOrderedDict(standards),
    )


def issues(*entries: tuple[str, str, str]) -> FrozenList[Issue]:
    return FrozenList(
        Issue(path, f"{problem} (exception rule `drift:{key}`)", f"drift:{key}")
        for path, key, problem in entries
    )


STANDARD_PYPROJECT = """
[tool.ruff]
preview = true
[tool.ruff.lint]
select = ["ALL"]
ignore = ["D"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"os.environ".msg = "x"
"sys.argv".msg = "y"
[tool.basedpyright]
typeCheckingMode = "all"
reportAny = "error"
[tool.pytest]
addopts = ["--a", "--b"]
[tool.mutmut]
pytest_add_cli_args = ["--m"]
[[tool.importlinter.contracts]]
type = "layers"
exhaustive = true
"""
STANDARD_CONFTEST = """
from hypothesis import settings
settings.register_profile("fast", max_examples=10)
settings.register_profile("full", max_examples=1000)
"""
PYTHON_STANDARDS = FrozenOrderedDict({
    "python/pyproject.toml": STANDARD_PYPROJECT,
    "python/conftest.py": STANDARD_CONFTEST,
})


def test_python_project_matching_the_standard_has_no_drift() -> None:
    project = {
        "pyproject.toml": STANDARD_PYPROJECT,
        "tests/conftest.py": STANDARD_CONFTEST,
    }
    assert tuple(python_drift(snapshot(project, PYTHON_STANDARDS))) == ()


def test_python_project_without_sections_reports_what_it_needs() -> None:
    found = tuple(
        python_drift(snapshot({"pyproject.toml": ""}, PYTHON_STANDARDS))
    )
    assert found == issues(
        (
            "pyproject.toml",
            "tool.pytest.addopts:--a",
            "tool.pytest.addopts lacks `--a`",
        ),
        (
            "pyproject.toml",
            "tool.pytest.addopts:--b",
            "tool.pytest.addopts lacks `--b`",
        ),
        (
            "pyproject.toml",
            "tool.mutmut.pytest_add_cli_args:--m",
            "tool.mutmut.pytest_add_cli_args lacks `--m`",
        ),
        (
            "pyproject.toml",
            "tool.importlinter.layers",
            "tool.importlinter lacks an exhaustive layers contract",
        ),
        (
            "tests/conftest.py",
            "hypothesis.fast",
            "hypothesis `fast` runs fewer than 10 cases",
        ),
        (
            "tests/conftest.py",
            "hypothesis.full",
            "hypothesis `full` runs fewer than 1000 cases",
        ),
    )


WEAK_PYPROJECT = """
[tool.ruff]
exclude = ["a"]
extend-exclude = ["b"]
[tool.ruff.lint]
select = ["E"]
ignore = ["D", "E501"]
extend-ignore = ["F"]
extend-per-file-ignores = {"x" = ["F"]}
exclude = ["c"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "PLR2004"]
"src/**" = ["T201"]
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"sys.argv".msg = "y"
[tool.basedpyright]
typeCheckingMode = "standard"
reportAny = false
reportUnknown = "warning"
strictListInference = true
exclude = ["d"]
ignore = ["e"]
[tool.pytest]
addopts = ["--b"]
[tool.mutmut]
do_not_mutate = ["x"]
only_mutate = ["y"]
do_not_mutate_patterns = ["z"]
pytest_add_cli_args = ["--m"]
[[tool.importlinter.contracts]]
type = "layers"
exhaustive = false
[[tool.importlinter.contracts]]
type = "forbidden"
exhaustive = true
"""
WEAK_CONFTEST = """
from hypothesis import settings
settings.register_profile("fast", max_examples=9)
settings.register_profile("full", max_examples=5000)
"""


def test_python_project_that_weakens_every_check() -> None:
    project = {
        "pyproject.toml": WEAK_PYPROJECT,
        "pkg/tests/conftest.py": WEAK_CONFTEST,
    }
    found = tuple(python_drift(snapshot(project, PYTHON_STANDARDS)))
    lint = "tool.ruff.lint"
    pyright = "tool.basedpyright"
    path = "pyproject.toml"
    assert found == issues(
        (path, f"{lint}.select:ALL", f"{lint}.select lacks `ALL`"),
        (path, f"{lint}.ignore:E501", f"{lint}.ignore adds `E501`"),
        (
            path,
            f"{lint}.per-file-ignores.tests/**:PLR2004",
            f"{lint}.per-file-ignores.tests/** adds `PLR2004`",
        ),
        (
            path,
            f"{lint}.per-file-ignores.src/**:T201",
            f"{lint}.per-file-ignores.src/** adds `T201`",
        ),
        (
            path,
            f"{lint}.flake8-tidy-imports.banned-api:os.environ",
            f"{lint}.flake8-tidy-imports.banned-api lacks `os.environ`",
        ),
        (
            path,
            f"{lint}.extend-ignore",
            f"{lint}.extend-ignore hides code from checks",
        ),
        (
            path,
            f"{lint}.extend-per-file-ignores",
            f"{lint}.extend-per-file-ignores hides code from checks",
        ),
        (path, f"{lint}.exclude", f"{lint}.exclude hides code from checks"),
        (path, "tool.ruff.exclude", "tool.ruff.exclude hides code from checks"),
        (
            path,
            "tool.ruff.extend-exclude",
            "tool.ruff.extend-exclude hides code from checks",
        ),
        (path, "tool.ruff.preview", "tool.ruff.preview is off"),
        (
            path,
            f"{pyright}.typeCheckingMode",
            f"{pyright}.typeCheckingMode is not `all`",
        ),
        (
            path,
            f"{pyright}.reportUnknown",
            f"{pyright}.reportUnknown weakens a check",
        ),
        (
            path,
            f"{pyright}.exclude",
            f"{pyright}.exclude hides code from checks",
        ),
        (path, f"{pyright}.ignore", f"{pyright}.ignore hides code from checks"),
        (path, "tool.pytest.addopts:--a", "tool.pytest.addopts lacks `--a`"),
        (
            path,
            "tool.mutmut.do_not_mutate",
            "tool.mutmut.do_not_mutate hides code from checks",
        ),
        (
            path,
            "tool.mutmut.only_mutate",
            "tool.mutmut.only_mutate hides code from checks",
        ),
        (
            path,
            "tool.mutmut.do_not_mutate_patterns",
            "tool.mutmut.do_not_mutate_patterns hides code from checks",
        ),
        (
            path,
            "tool.importlinter.layers",
            "tool.importlinter lacks an exhaustive layers contract",
        ),
        (
            "pkg/tests/conftest.py",
            "hypothesis.fast",
            "hypothesis `fast` runs fewer than 10 cases",
        ),
    )


def test_python_drift_ignores_layers_when_the_standard_has_none() -> None:
    standards = {"python/pyproject.toml": "", "python/conftest.py": ""}
    assert (
        tuple(python_drift(snapshot({"pyproject.toml": ""}, standards))) == ()
    )


def test_python_profiles_merge_across_conftests() -> None:
    project = {
        "pyproject.toml": STANDARD_PYPROJECT,
        "a/conftest.py": WEAK_CONFTEST,
        "b/conftest.py": STANDARD_CONFTEST,
    }
    assert tuple(python_drift(snapshot(project, PYTHON_STANDARDS))) == ()


def test_hypothesis_profiles() -> None:
    text = (
        "settings.register_profile('a', max_examples=3, deadline=None)\n"
        "settings.register_profile('b', deadline=None)\n"
        "settings.register_profile(name, max_examples=4)\n"
        "settings.register_profile('c', max_examples=n)\n"
        "settings.register_profile(1, max_examples=5)\n"
        "settings.register_profile()\n"
        "register_profile('d', max_examples=6)\n"
        "other.thing('e', max_examples=7)\n"
    )
    assert hypothesis_profiles(text) == {"a": 3}
    assert hypothesis_profiles(None) == {}


STANDARD_CARGO = """
[lints.rust]
unsafe_code = "deny"
warnings = "forbid"
[lints.clippy]
all = { level = "deny", priority = -1 }
"""
STANDARD_CLIPPY = """
disallowed-types = [{ path = "core::cell::Cell", reason = "x" }, { path = "a::B" }]
disallowed-methods = [{ path = "a::f" }, { reason = "no path" }]
"""
RUST_STANDARDS = FrozenOrderedDict({
    "rust/Cargo.fragment.toml": STANDARD_CARGO,
    "rust/clippy.toml": STANDARD_CLIPPY,
})


def test_rust_project_matching_the_standard_has_no_drift() -> None:
    project = {
        "Cargo.toml": STANDARD_CARGO,
        "clippy.toml": STANDARD_CLIPPY,
        ".cargo/config.toml": '[env]\nPROPTEST_CASES = "16"\n',
    }
    assert tuple(rust_drift(snapshot(project, RUST_STANDARDS))) == ()


def test_rust_project_without_config_has_no_drift() -> None:
    assert tuple(rust_drift(snapshot({}, RUST_STANDARDS))) == ()


def test_rust_project_that_weakens_every_check() -> None:
    project = {
        "Cargo.toml": """
[workspace.lints.rust]
unsafe_code = "warn"
warnings = "deny"
unused = "allow"
missing_docs = "deny"
[workspace.lints.clippy]
all = "deny"
pedantic = { level = "warn" }
""",
        ".clippy.toml": 'disallowed-types = [{ path = "a::B" }]\n',
        ".cargo/mutants.toml": 'exclude_globs = ["x"]\nexclude_re = ["y"]\nexamine_globs = ["z"]\nexamine_re = ["w"]\n',
        ".cargo/config.toml": '[env]\nPROPTEST_CASES = { value = "15" }\n',
    }
    found = tuple(rust_drift(snapshot(project, RUST_STANDARDS)))
    assert found == issues(
        (
            "Cargo.toml",
            "lints.rust.unsafe_code",
            "lints.rust.unsafe_code is weaker than `deny`",
        ),
        (
            "Cargo.toml",
            "lints.rust.warnings",
            "lints.rust.warnings is weaker than `forbid`",
        ),
        ("Cargo.toml", "lints.rust.unused", "lints.rust.unused relaxes a lint"),
        (
            "Cargo.toml",
            "lints.clippy.pedantic",
            "lints.clippy.pedantic relaxes a lint",
        ),
        (
            "clippy.toml",
            "disallowed-types:core::cell::Cell",
            "disallowed-types lacks `core::cell::Cell`",
        ),
        (
            "clippy.toml",
            "disallowed-methods:a::f",
            "disallowed-methods lacks `a::f`",
        ),
        (
            ".cargo/mutants.toml",
            "mutants.exclude_globs",
            "mutants.exclude_globs hides code from checks",
        ),
        (
            ".cargo/mutants.toml",
            "mutants.exclude_re",
            "mutants.exclude_re hides code from checks",
        ),
        (
            ".cargo/mutants.toml",
            "mutants.examine_globs",
            "mutants.examine_globs hides code from checks",
        ),
        (
            ".cargo/mutants.toml",
            "mutants.examine_re",
            "mutants.examine_re hides code from checks",
        ),
        (
            ".cargo/config.toml",
            "env.PROPTEST_CASES",
            "PROPTEST_CASES is below 16",
        ),
    )


@pytest.mark.parametrize(
    "config",
    [
        "[profile.default]\nretries = 2\n",
        '[[profile.ci.overrides]]\nfilter = "test(a)"\nretries = 1\n',
    ],
)
def test_rust_nextest_retries_are_drift(config: str) -> None:
    found = tuple(
        rust_drift(snapshot({".config/nextest.toml": config}, RUST_STANDARDS))
    )
    assert found == issues((
        ".config/nextest.toml",
        "nextest.retries",
        "retries hide failing tests; list each flaky test in exceptions.toml",
    ))


def test_rust_nextest_config_without_retries_has_no_drift() -> None:
    config = (
        '[profile.default]\nslow-timeout = "60s"\n'
        '[[profile.default.overrides]]\nfilter = "test(a)"\nthreads-required = 2\n'
    )
    project = {".config/nextest.toml": config}
    assert tuple(rust_drift(snapshot(project, RUST_STANDARDS))) == ()


def test_rust_prefers_package_lints_and_clippy_toml() -> None:
    project = {
        "Cargo.toml": '[lints.rust]\nunsafe_code = "deny"\nwarnings = "forbid"\n[lints.clippy]\nall = "forbid"\n[workspace.lints.rust]\nunsafe_code = "allow"\n',
        "clippy.toml": STANDARD_CLIPPY,
        ".clippy.toml": "",
    }
    assert tuple(rust_drift(snapshot(project, RUST_STANDARDS))) == ()


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ('[env]\nPROPTEST_CASES = "8"\n', 8),
        ("[env]\nPROPTEST_CASES = 8\n", 8),
        ('[env]\nPROPTEST_CASES = { value = "9" }\n', 9),
        ('[env]\nPROPTEST_CASES = "many"\n', None),
        ("[env]\nPROPTEST_CASES = -1\n", None),
        ("", None),
    ],
)
def test_proptest_cases(config: str, expected: int | None) -> None:
    assert proptest_cases(parse_toml(config)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("deny", "deny"),
        ({"level": "warn"}, "warn"),
        ({"level": 1}, ""),
        (3, ""),
    ],
)
def test_level(value: object, expected: str) -> None:
    assert level(value) == expected


def test_biome_levels_flatten_groups() -> None:
    rules = {
        "recommended": "on",
        "style": {"noVar": "off", "useConst": {"level": "warn"}},
    }
    assert biome_levels(rules) == {
        "recommended": "on",
        "style/noVar": "off",
        "style/useConst": "warn",
    }


STANDARD_BIOME = json.dumps({
    "linter": {
        "rules": {
            "preset": "strict",
            "style": {
                "noVar": "error",
                "noRestrictedGlobals": {
                    "options": {"deniedGlobals": {"Date": "x"}}
                },
                "noRestrictedImports": {"options": {"paths": {"fs": "y"}}},
                "useWeak": "off",
            },
        }
    },
    "plugins": ["./biome-plugins/a.grit", {"path": "./biome-plugins/b.grit"}],
    "overrides": [
        {
            "includes": ["tests/**"],
            "linter": {"rules": {"style": {"noMagic": "off"}}},
        }
    ],
})
STANDARD_TSCONFIG = json.dumps({
    "compilerOptions": {"strict": True, "noImplicitAny": True, "target": "x"}
})
STANDARD_STRYKER = json.dumps({
    "thresholds": {"break": 100},
    "mutate": ["src/**", "!src/**/*.test.ts"],
})
TYPESCRIPT_STANDARDS = FrozenOrderedDict({
    "typescript/biome.json": STANDARD_BIOME,
    "typescript/tsconfig.base.json": STANDARD_TSCONFIG,
    "typescript/stryker.config.json": STANDARD_STRYKER,
    "typescript/knip.json": json.dumps({
        "ignore": ["dist/**"],
        "ignoreBinaries": ["tsc"],
    }),
    "typescript/profiles/fast.ts": "export default { numRuns: 10 };",
    "typescript/profiles/full.ts": "export default { numRuns:1000 };",
    "typescript/profiles/mutation.ts": "export default {};",
})


def test_typescript_project_matching_the_standard_has_no_drift() -> None:
    project = {
        "biome.json": STANDARD_BIOME,
        "tsconfig.json": json.dumps({
            "compilerOptions": {"noImplicitAny": True}
        }),
        "stryker.config.json": STANDARD_STRYKER,
        "knip.json": json.dumps({"ignore": ["dist/**"]}),
        "profiles/fast.ts": "{ numRuns: 10 }",
        "profiles/full.ts": "{ numRuns: 1000 }",
    }
    assert (
        tuple(typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS))) == ()
    )


def test_typescript_project_without_config() -> None:
    found = tuple(typescript_drift(snapshot({}, TYPESCRIPT_STANDARDS)))
    assert found == issues(
        (
            "profiles",
            "fast-check.fast",
            "fast-check `fast` runs fewer than 10 cases",
        ),
        (
            "profiles",
            "fast-check.full",
            "fast-check `full` runs fewer than 1000 cases",
        ),
    )


def test_typescript_project_that_weakens_every_check() -> None:
    biome: dict[str, object] = {
        "linter": {
            "enabled": False,
            "rules": {
                "preset": "recommended",
                "style": {
                    "noVar": "warn",
                    "useWeak": "off",
                    "useOther": {"level": "info"},
                    "useStrong": "error",
                    "noRestrictedGlobals": {"options": {"deniedGlobals": {}}},
                },
                "suspicious": "off",
            },
        },
        "plugins": ["../elsewhere/a.grit"],
        "overrides": [
            {
                "includes": ["tests/**"],
                "linter": {"rules": {"style": {"noMagic": "off"}}},
            },
            {
                "includes": ["src/**", "lib/**"],
                "linter": {"rules": {"style": {"noVar": "warn"}}},
            },
            {
                "includes": ["x/**"],
                "linter": {"rules": {"style": {"noVar": "error"}}},
            },
        ],
    }
    project = {
        "biome.jsonc": json.dumps(biome),
        "tsconfig.json": json.dumps({
            "compilerOptions": {
                "strict": False,
                "noImplicitAny": False,
                "target": False,
            }
        }),
        "stryker.config.json": json.dumps({
            "thresholds": {"break": 80},
            "mutate": ["src/**", "!src/**/*.test.ts", "!src/skip.ts", "lib/**"],
        }),
        "knip.jsonc": json.dumps({
            "ignore": ["dist/**", "gen/**"],
            "ignoreDependencies": "lodash",
            "other": ["x"],
        }),
        "profiles/fast.ts": "{ numRuns: 9 }",
        "profiles/full.ts": "{ numRuns: 5000 }",
    }
    rules = "linter.rules"
    found = tuple(typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS)))
    assert found == issues(
        ("biome.json", f"{rules}.preset", f"{rules}.preset is not `strict`"),
        ("biome.json", "linter.enabled", "the linter is disabled"),
        ("biome.json", "plugins:b.grit", "plugins lacks `b.grit`"),
        (
            "biome.json",
            f"{rules}.style/noVar",
            f"{rules}.style/noVar is `warn`",
        ),
        (
            "biome.json",
            f"{rules}.style/useOther",
            f"{rules}.style/useOther is `info`",
        ),
        ("biome.json", f"{rules}.suspicious", f"{rules}.suspicious is `off`"),
        (
            "biome.json",
            f"{rules}.style/noRestrictedGlobals.deniedGlobals:Date",
            f"{rules}.style/noRestrictedGlobals.deniedGlobals lacks `Date`",
        ),
        (
            "biome.json",
            f"{rules}.style/noRestrictedImports.paths:fs",
            f"{rules}.style/noRestrictedImports.paths lacks `fs`",
        ),
        (
            "biome.json",
            "overrides.src/**,lib/**.style/noVar",
            "override for src/**,lib/** sets style/noVar to `warn`",
        ),
        (
            "tsconfig.json",
            "compilerOptions.strict",
            "compilerOptions.strict is false",
        ),
        (
            "tsconfig.json",
            "compilerOptions.noImplicitAny",
            "compilerOptions.noImplicitAny is false",
        ),
        (
            "stryker.config.json",
            "thresholds.break",
            "thresholds.break is below 100",
        ),
        (
            "stryker.config.json",
            "mutate:!src/skip.ts",
            "mutate adds `!src/skip.ts`",
        ),
        (
            "profiles",
            "fast-check.fast",
            "fast-check `fast` runs fewer than 10 cases",
        ),
        ("knip.json", "ignore:gen/**", "ignore adds `gen/**`"),
        (
            "knip.json",
            "ignoreDependencies:lodash",
            "ignoreDependencies adds `lodash`",
        ),
    )


def test_typescript_strict_off_without_a_standard_flag() -> None:
    standards = dict(TYPESCRIPT_STANDARDS) | {
        "typescript/tsconfig.base.json": json.dumps({"compilerOptions": {}})
    }
    project = {
        "tsconfig.json": json.dumps({"compilerOptions": {"strict": False}}),
        "profiles/fast.ts": "{ numRuns: 10 }",
        "profiles/full.ts": "{ numRuns: 1000 }",
    }
    assert tuple(typescript_drift(snapshot(project, standards))) == issues((
        "tsconfig.json",
        "compilerOptions.strict",
        "compilerOptions.strict is false",
    ))


def test_stryker_threshold_missing_or_not_a_number() -> None:
    standards = dict(TYPESCRIPT_STANDARDS) | {
        "typescript/profiles/fast.ts": "",
        "typescript/profiles/full.ts": "",
    }
    for thresholds in ('{"mutate": []}', '{"thresholds": {"break": "100"}}'):
        project = {"stryker.config.json": thresholds}
        assert tuple(typescript_drift(snapshot(project, standards))) == issues((
            "stryker.config.json",
            "thresholds.break",
            "thresholds.break is below 100",
        ))
    standards |= {
        "typescript/stryker.config.json": json.dumps({
            "thresholds": {"break": "x"}
        })
    }
    project = {"stryker.config.json": json.dumps({"mutate": ["src/**"]})}
    assert tuple(typescript_drift(snapshot(project, standards))) == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{ numRuns: 12 }", 12),
        ("{numRuns:3}", 3),
        ("{ runs: 4 }", None),
        (None, None),
    ],
)
def test_runs(text: str | None, expected: int | None) -> None:
    assert runs(text) == expected


def test_rust_lint_missing_from_the_project() -> None:
    standards = RUST_STANDARDS | {
        "rust/Cargo.fragment.toml": '[lints.rust]\nunsafe_code = "warn"\nodd = "sometimes"\n'
    }
    project = {"Cargo.toml": '[lints.rust]\nother = "deny"\nwild = "maybe"\n'}
    assert tuple(rust_drift(snapshot(project, standards))) == issues(
        (
            "Cargo.toml",
            "lints.rust.unsafe_code",
            "lints.rust.unsafe_code is weaker than `warn`",
        ),
        ("Cargo.toml", "lints.rust.wild", "lints.rust.wild relaxes a lint"),
    )


def test_rust_clippy_toml_is_checked() -> None:
    project = {"clippy.toml": 'disallowed-methods = [{ path = "a::f" }]\n'}
    assert tuple(rust_drift(snapshot(project, RUST_STANDARDS))) == issues(
        (
            "clippy.toml",
            "disallowed-types:core::cell::Cell",
            "disallowed-types lacks `core::cell::Cell`",
        ),
        (
            "clippy.toml",
            "disallowed-types:a::B",
            "disallowed-types lacks `a::B`",
        ),
    )


def test_typescript_biome_json_and_knip_json_are_checked() -> None:
    project = {
        "biome.json": json.dumps({
            "linter": {"enabled": False, "rules": {"preset": "strict"}},
            "plugins": ["a.grit", "b.grit"],
        }),
        "knip.json": json.dumps({"ignore": ["gen/**"]}),
        "profiles/fast.ts": "{ numRuns: 10 }",
        "profiles/full.ts": "{ numRuns: 1000 }",
    }
    standards = TYPESCRIPT_STANDARDS | {
        "typescript/biome.json": json.dumps({
            "linter": {"rules": {"preset": "strict"}}
        })
    }
    assert tuple(typescript_drift(snapshot(project, standards))) == issues(
        ("biome.json", "linter.enabled", "the linter is disabled"),
        ("knip.json", "ignore:gen/**", "ignore adds `gen/**`"),
    )
