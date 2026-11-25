import json
lazy from collections.abc import Mapping, Sequence

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import (
    Snapshot,
    hypothesis_profiles,
    level,
    proptest_cases,
    python_drift,
    rust_drift,
    typescript_drift,
    vitest_runs,
)
from checks.core.exceptions import Issue
from checks.core.values import entries, parse_toml, strings, table


def snapshot(
    project: Mapping[str, str],
    standards: Mapping[str, str],
    files: Sequence[str] = (),
    resolved: Mapping[str, str] | None = None,
) -> Snapshot:
    return Snapshot(
        FrozenList(files or tuple(project)),
        FrozenOrderedDict(project),
        FrozenOrderedDict(standards),
        FrozenOrderedDict(resolved or {}),
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


STANDARD_OXLINT_SOURCE = """import cloudflare from "@cloudflare/oxlint-config";

export default defineConfig({ extends: [cloudflare] });
"""
# A project config that extends the standard's, as check.sh evaluates it.
EXTENDING = """import standard from "#standards/oxlint";
import { defineConfig } from "oxlint";

export default defineConfig({
	extends: [standard],
	rules: { "react/jsx-max-depth": "error" },
});
"""
# The standard's config as `oxlint --print-config` resolves it: extends
# flattened, categories expanded into rules, levels as allow, warn and deny.
STANDARD_OXLINT: Mapping[str, object] = FrozenOrderedDict({
    "plugins": ["typescript", "react", "jsx-a11y"],
    "jsPlugins": [
        {
            "name": "standards",
            "specifier": "file:///run/oxlint-plugins/index.ts",
        },
        {"name": "quality", "specifier": "file:///install/quality/index.js"},
    ],
    "categories": {"correctness": "deny", "style": "deny"},
    "rules": {
        "no-bitwise": "deny",
        "no-console": "warn",
        "typescript/no-explicit-any": ["deny", {"fixToUnknown": False}],
        "react/rules-of-hooks": "deny",
        "jsx_a11y/alt-text": "deny",
        "no-magic-numbers": "deny",
        "no-restricted-globals": [
            "deny",
            {"name": "process", "message": "ambient"},
            {"name": "fetch", "message": "boundary"},
        ],
        "no-restricted-imports": [
            "deny",
            {"paths": [{"name": "lodash", "message": "x"}, "fs"]},
        ],
    },
    "overrides": [
        {
            "files": ["**/*.test.ts"],
            "env": None,
            "globals": None,
            "plugins": None,
            "rules": {"no-magic-numbers": "allow"},
        }
    ],
    "options": {"typeAware": True, "respectEslintDisableDirectives": False},
    "ignorePatterns": [],
})
STANDARD_TSCONFIG = json.dumps({
    "compilerOptions": {"strict": True, "noImplicitAny": True, "target": "x"}
})
STANDARD_STRYKER = json.dumps({
    "thresholds": {"break": 100},
    "mutate": ["src/**", "!src/**/*.test.ts"],
})
TYPESCRIPT_STANDARDS = FrozenOrderedDict({
    "typescript/oxlint.config.ts": STANDARD_OXLINT_SOURCE,
    "typescript/tsconfig.base.json": STANDARD_TSCONFIG,
    "typescript/stryker.config.json": STANDARD_STRYKER,
    "typescript/knip.json": json.dumps({
        "ignore": ["dist/**"],
        "ignoreBinaries": ["tsc"],
    }),
    "typescript/vitest.config.ts": (
        "const modes = {\n"
        "\tfast: { runs: 10 },\n"
        "\tfull: {runs:1000},\n"
        "\tmutation: { runs: 10, seed: 42 },\n"
        "} as const;\n"
    ),
})
KEPT_RUNS = (
    "fast: { runs: 10 }, full: { runs: 1000 }, mutation: { runs: 10, seed: 42 }"
)
OXLINT = "oxlint.config.ts"
NOT_EXTENDED = (
    OXLINT,
    "extends",
    "oxlint.config.ts doesn't extend the standard's, imported from `#standards/oxlint`",
)


def oxlint_drift_of(
    source: str, project: Mapping[str, object]
) -> FrozenList[Issue]:
    files = {OXLINT: source, "vitest.config.ts": KEPT_RUNS}
    resolved = {
        OXLINT: json.dumps(dict(project)),
        "typescript/oxlint.config.ts": json.dumps(dict(STANDARD_OXLINT)),
    }
    return FrozenList(
        typescript_drift(snapshot(files, TYPESCRIPT_STANDARDS, (), resolved))
    )


def test_typescript_project_matching_the_standard_has_no_drift() -> None:
    project = {
        OXLINT: EXTENDING,
        "tsconfig.json": json.dumps({
            "compilerOptions": {"noImplicitAny": True}
        }),
        "stryker.config.json": STANDARD_STRYKER,
        "knip.json": json.dumps({"ignore": ["dist/**"]}),
        "vitest.config.ts": KEPT_RUNS,
    }
    resolved = {
        OXLINT: json.dumps(dict(STANDARD_OXLINT)),
        "typescript/oxlint.config.ts": json.dumps(dict(STANDARD_OXLINT)),
    }
    found = typescript_drift(
        snapshot(project, TYPESCRIPT_STANDARDS, (), resolved)
    )
    assert tuple(found) == ()


def test_an_oxlint_config_that_only_adds_or_raises_rules_has_no_drift() -> None:
    standard_rules = table(STANDARD_OXLINT["rules"])
    raised = dict(STANDARD_OXLINT) | {
        "plugins": [*strings(STANDARD_OXLINT["plugins"]), "promise"],
        "jsPlugins": [
            *entries(STANDARD_OXLINT["jsPlugins"]),
            {"name": "local", "specifier": "file:///project/local.ts"},
        ],
        "categories": {"correctness": "deny", "style": "deny", "perf": "deny"},
        "rules": dict(standard_rules)
        | {
            "no-console": "deny",
            "react/jsx-max-depth": ["deny", {"max": 3}],
            "nursery-rule": "allow",
            "no-restricted-globals": [
                *entries(standard_rules["no-restricted-globals"]),
                {"name": "window", "message": "x"},
            ],
        },
        "overrides": [
            *entries(STANDARD_OXLINT["overrides"]),
            {
                "files": ["src/**"],
                "rules": {"no-console": "deny", "nursery-rule": "allow"},
            },
        ],
    }
    assert oxlint_drift_of(EXTENDING, raised) == ()


def test_an_oxlint_config_that_weakens_every_check() -> None:
    weak = {
        "plugins": ["typescript"],
        "jsPlugins": [
            {"name": "quality", "specifier": "file:///install/quality/index.js"}
        ],
        "categories": {"style": "warn"},
        "rules": {
            "no-bitwise": "warn",
            "no-console": "warn",
            "typescript/no-explicit-any": ["allow", {"fixToUnknown": False}],
            "no-magic-numbers": "deny",
            "no-restricted-globals": ["deny", "process"],
            "no-restricted-imports": ["deny", {"paths": ["fs"]}],
        },
        "overrides": [
            *entries(STANDARD_OXLINT["overrides"]),
            {"files": ["src/**", "lib/**"], "rules": {"no-bitwise": "allow"}},
            {"files": ["x/**"], "rules": {"no-bitwise": "deny"}},
        ],
        "options": {
            "typeAware": False,
            "respectEslintDisableDirectives": False,
        },
        "ignorePatterns": ["gen/**"],
    }
    restricted = "rules.eslint/no-restricted"
    assert oxlint_drift_of(STANDARD_OXLINT_SOURCE + "\n", weak) == issues(
        NOT_EXTENDED,
        (
            OXLINT,
            "categories.correctness",
            "categories.correctness is `off`, weaker than `deny`",
        ),
        (
            OXLINT,
            "categories.style",
            "categories.style is `warn`, weaker than `deny`",
        ),
        (
            OXLINT,
            "rules.eslint/no-bitwise",
            "rules.eslint/no-bitwise is `warn`, weaker than `deny`",
        ),
        (
            OXLINT,
            "rules.typescript/no-explicit-any",
            "rules.typescript/no-explicit-any is `allow`, weaker than `deny`",
        ),
        (
            OXLINT,
            "rules.react-hooks/rules-of-hooks",
            "rules.react-hooks/rules-of-hooks is `off`, weaker than `deny`",
        ),
        (
            OXLINT,
            "rules.jsx-a11y/alt-text",
            "rules.jsx-a11y/alt-text is `off`, weaker than `deny`",
        ),
        (OXLINT, "jsPlugins:standards", "jsPlugins lacks `standards`"),
        (
            OXLINT,
            f"{restricted}-globals:fetch",
            f"{restricted}-globals lacks `fetch`",
        ),
        (
            OXLINT,
            f"{restricted}-imports:lodash",
            f"{restricted}-imports lacks `lodash`",
        ),
        (
            OXLINT,
            "overrides.src/**,lib/**.eslint/no-bitwise",
            "override for src/**,lib/** sets eslint/no-bitwise to `allow`",
        ),
        (
            OXLINT,
            "options.typeAware",
            "options.typeAware is `false`, not `true`",
        ),
        (OXLINT, "ignorePatterns:gen/**", "ignorePatterns adds `gen/**`"),
    )


def test_an_oxlint_config_weakening_a_scoped_plugins_rule() -> None:
    files = {OXLINT: EXTENDING, "vitest.config.ts": KEPT_RUNS}
    resolved = {
        OXLINT: json.dumps({"rules": {"@nkzw/no-instanceof": "allow"}}),
        "typescript/oxlint.config.ts": json.dumps({
            "rules": {"@nkzw/no-instanceof": "deny"}
        }),
    }
    found = typescript_drift(
        snapshot(files, TYPESCRIPT_STANDARDS, (), resolved)
    )
    assert tuple(found) == issues((
        OXLINT,
        "rules.@nkzw/no-instanceof",
        "rules.@nkzw/no-instanceof is `allow`, weaker than `deny`",
    ))


def test_the_standard_oxlint_config_itself_has_no_drift() -> None:
    assert oxlint_drift_of(STANDARD_OXLINT_SOURCE, STANDARD_OXLINT) == ()


def test_an_oxlint_config_importing_the_standard_must_extend_it() -> None:
    source = (
        'import standard from "#standards/oxlint";\n'
        'import other from "./other.ts";\n\n'
        "export default { extends: [other], rules: standard.rules };\n"
    )
    assert oxlint_drift_of(source, STANDARD_OXLINT) == issues(NOT_EXTENDED)


def test_an_oxlint_config_left_unresolved_is_checked_for_extends_alone() -> (
    None
):
    project = {OXLINT: "export default {};\n", "vitest.config.ts": KEPT_RUNS}
    found = typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS))
    assert tuple(found) == issues(NOT_EXTENDED)


def test_typescript_project_without_config() -> None:
    # Without its own vitest config, a project's tests run on the standard's.
    assert tuple(typescript_drift(snapshot({}, TYPESCRIPT_STANDARDS))) == ()


def test_a_vite_config_without_the_modes_runs_fewer_cases() -> None:
    # vitest reads vite.config.ts without a vitest.config.ts, so it is the
    # project's own vitest config.
    project = {"vite.config.ts": "export default { test: {} };\n"}
    found = tuple(typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS)))
    assert found == issues(
        (
            "vite.config.ts",
            "arbitrary.fast",
            "arbitrary `fast` runs fewer than 10 cases",
        ),
        (
            "vite.config.ts",
            "arbitrary.full",
            "arbitrary `full` runs fewer than 1000 cases",
        ),
        (
            "vite.config.ts",
            "arbitrary.mutation",
            "arbitrary `mutation` runs fewer than 10 cases",
        ),
    )


def test_typescript_project_that_weakens_every_check() -> None:
    project = {
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
        "vitest.config.ts": (
            "fast: { runs: 9 }, full: { runs: 5000 }, mutation: { runs: 10 }"
        ),
    }
    found = tuple(typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS)))
    assert found == issues(
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
            "vitest.config.ts",
            "arbitrary.fast",
            "arbitrary `fast` runs fewer than 10 cases",
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
        "vitest.config.ts": KEPT_RUNS,
    }
    assert tuple(typescript_drift(snapshot(project, standards))) == issues((
        "tsconfig.json",
        "compilerOptions.strict",
        "compilerOptions.strict is false",
    ))


def test_stryker_threshold_missing_or_not_a_number() -> None:
    standards = dict(TYPESCRIPT_STANDARDS) | {"typescript/vitest.config.ts": ""}
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
        (
            "fast: { runs: 12 }, full: {runs:3, seed: 1}",
            {"fast": 12, "full": 3},
        ),
        ("mutation: { seed: 42, runs: 4 }", {"mutation": 4}),
        ("fast: { seed: 4 }, full: 3", {}),
        (None, {}),
    ],
)
def test_vitest_runs(text: str | None, expected: Mapping[str, int]) -> None:
    assert vitest_runs(text) == expected


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


def test_typescript_knip_json_is_checked() -> None:
    project = {
        "knip.json": json.dumps({"ignore": ["gen/**"]}),
        "vitest.config.ts": KEPT_RUNS,
    }
    found = typescript_drift(snapshot(project, TYPESCRIPT_STANDARDS))
    assert tuple(found) == issues((
        "knip.json",
        "ignore:gen/**",
        "ignore adds `gen/**`",
    ))
