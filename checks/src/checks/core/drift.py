import ast
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import Issue
from checks.core.values import (
    entries,
    is_list,
    lookup,
    parse_json,
    parse_toml,
    strings,
    table,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

WEAK = FrozenOrderedSet((
    "off",
    "none",
    "info",
    "information",
    "hint",
    "warn",
    "warning",
    "allow",
))
RANKS = FrozenOrderedDict({
    "allow": 0,
    "warn": 1,
    "expect": 1,
    "deny": 2,
    "forbid": 3,
})
PROPTEST_CASES = 16
# A mode of vitest.config.ts and the runs of its property tests, as
# `fast: { runs: 10 }`.
MODE_RUNS = re.compile(r"\b(\w+):\s*\{[^{}]*?\bruns:\s*(\d+)")
PROJECT_FILES = FrozenOrderedDict({
    "python": FrozenList(("pyproject.toml",)),
    "rust": FrozenList((
        "Cargo.toml",
        "clippy.toml",
        ".clippy.toml",
        ".cargo/mutants.toml",
        ".cargo/config.toml",
        ".config/nextest.toml",
    )),
    "typescript": FrozenList((
        "oxlint.config.ts",
        "tsconfig.json",
        "stryker.config.json",
        "knip.json",
        "knip.jsonc",
        "vitest.config.ts",
    )),
})
STANDARD_FILES = FrozenOrderedDict({
    "python": FrozenList(("python/pyproject.toml", "python/conftest.py")),
    "rust": FrozenList(("rust/Cargo.fragment.toml", "rust/clippy.toml")),
    "typescript": FrozenList((
        "typescript/oxlint.config.ts",
        "typescript/tsconfig.base.json",
        "typescript/stryker.config.json",
        "typescript/knip.json",
        "typescript/vitest.config.ts",
    )),
})


@dataclass(frozen=True, slots=True)
class Snapshot:
    files: FrozenList[str]
    project: FrozenOrderedDict[str, str]
    standards: FrozenOrderedDict[str, str]
    # The project's and the standard's configs, as their tools resolve them,
    # under the path of each.
    resolved: FrozenOrderedDict[str, str] = field(
        default_factory=FrozenOrderedDict
    )

    def toml(self, path: str) -> Mapping[str, object]:
        return parse_toml(self.project.get(path))

    def json(self, path: str) -> Mapping[str, object]:
        return parse_json(self.project.get(path))

    def standard_toml(self, path: str) -> Mapping[str, object]:
        return parse_toml(self.standards.get(path))

    def standard_json(self, path: str) -> Mapping[str, object]:
        return parse_json(self.standards.get(path))


def drift(path: str, key: str, problem: str) -> Issue:
    rule = f"drift:{key}"
    return Issue(path, f"{problem} (exception rule `{rule}`)", rule)


def missing(
    path: str, key: str, standard: Sequence[str], project: Sequence[str]
) -> Iterator[Issue]:
    yield from (
        drift(path, f"{key}:{item}", f"{key} lacks `{item}`")
        for item in standard
        if item not in project
    )


def extra(
    path: str, key: str, project: Sequence[str], standard: Sequence[str]
) -> Iterator[Issue]:
    yield from (
        drift(path, f"{key}:{item}", f"{key} adds `{item}`")
        for item in project
        if item not in standard
    )


def present(
    path: str, data: Mapping[str, object], keys: Sequence[str], prefix: str
) -> Iterator[Issue]:
    yield from (
        drift(path, f"{prefix}.{key}", f"{prefix}.{key} hides code from checks")
        for key in keys
        if data.get(key)
    )


def ruff_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    path, key = "pyproject.toml", "tool.ruff.lint"
    standard_lint, project_lint = (
        table(standard.get("lint")),
        table(project.get("lint")),
    )
    yield from missing(
        path,
        f"{key}.select",
        strings(standard_lint.get("select")),
        strings(project_lint.get("select")),
    )
    yield from extra(
        path,
        f"{key}.ignore",
        strings(project_lint.get("ignore")),
        strings(standard_lint.get("ignore")),
    )
    standard_files = table(standard_lint.get("per-file-ignores"))
    for glob, rules in table(project_lint.get("per-file-ignores")).items():
        yield from extra(
            path,
            f"{key}.per-file-ignores.{glob}",
            strings(rules),
            strings(standard_files.get(glob)),
        )
    banned = "flake8-tidy-imports.banned-api"
    yield from missing(
        path,
        f"{key}.{banned}",
        FrozenList(table(lookup(standard_lint, banned))),
        FrozenList(table(lookup(project_lint, banned))),
    )
    hidden = FrozenList(("extend-ignore", "extend-per-file-ignores", "exclude"))
    yield from present(path, project_lint, hidden, key)
    yield from present(
        path, project, FrozenList(("exclude", "extend-exclude")), "tool.ruff"
    )
    if standard.get("preview") is True and project.get("preview") is not True:
        yield drift(path, "tool.ruff.preview", "tool.ruff.preview is off")


def basedpyright_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    path, key = "pyproject.toml", "tool.basedpyright"
    mode = "typeCheckingMode"
    if project.get(mode) != standard.get(mode):
        yield drift(
            path, f"{key}.{mode}", f"{key}.{mode} is not `{standard.get(mode)}`"
        )
    yield from (
        drift(path, f"{key}.{name}", f"{key}.{name} weakens a check")
        for name, value in project.items()
        if name not in standard
        and (value is False or (isinstance(value, str) and value in WEAK))
    )
    yield from present(path, project, FrozenList(("exclude", "ignore")), key)


def hypothesis_profiles(text: str | None) -> FrozenOrderedDict[str, int]:
    if text is None:
        return FrozenOrderedDict()
    return FrozenOrderedDict(
        (name.value, examples.value)
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_profile"
        and node.args
        and isinstance(name := node.args[0], ast.Constant)
        and isinstance(name.value, str)
        for keyword in node.keywords
        if keyword.arg == "max_examples"
        and isinstance(examples := keyword.value, ast.Constant)
        and isinstance(examples.value, int)
    )


def intensity(
    path: str, key: str, standard: Mapping[str, int], project: Mapping[str, int]
) -> Iterator[Issue]:
    for name, value in standard.items():
        actual = project.get(name)
        if actual is None or actual < value:
            yield drift(
                path,
                f"{key}.{name}",
                f"{key} `{name}` runs fewer than {value} cases",
            )


def layered(data: Mapping[str, object]) -> bool:
    return any(
        table(contract).get("type") == "layers"
        and table(contract).get("exhaustive") is True
        for contract in entries(lookup(data, "tool.importlinter.contracts"))
    )


def python_drift(snapshot: Snapshot) -> Iterator[Issue]:
    path = "pyproject.toml"
    standard = snapshot.standard_toml("python/pyproject.toml")
    project = snapshot.toml(path)
    ruff = table(lookup(project, "tool.ruff"))
    if ruff:
        yield from ruff_drift(table(lookup(standard, "tool.ruff")), ruff)
    basedpyright = table(lookup(project, "tool.basedpyright"))
    if basedpyright:
        yield from basedpyright_drift(
            table(lookup(standard, "tool.basedpyright")), basedpyright
        )
    yield from missing(
        path,
        "tool.pytest.addopts",
        strings(lookup(standard, "tool.pytest.addopts")),
        strings(lookup(project, "tool.pytest.addopts")),
    )
    mutmut = table(lookup(project, "tool.mutmut"))
    yield from present(
        path,
        mutmut,
        FrozenList(("do_not_mutate", "only_mutate", "do_not_mutate_patterns")),
        "tool.mutmut",
    )
    yield from missing(
        path,
        "tool.mutmut.pytest_add_cli_args",
        strings(lookup(standard, "tool.mutmut.pytest_add_cli_args")),
        strings(mutmut.get("pytest_add_cli_args")),
    )
    if layered(standard) and not layered(project):
        yield drift(
            path,
            "tool.importlinter.layers",
            "tool.importlinter lacks an exhaustive layers contract",
        )
    conftests = FrozenList(
        file for file in snapshot.files if file.endswith("conftest.py")
    )
    profiles = FrozenOrderedDict(
        (name, value)
        for file in conftests
        for name, value in hypothesis_profiles(
            snapshot.project.get(file)
        ).items()
    )
    yield from intensity(
        conftests[0] if conftests else "tests/conftest.py",
        "hypothesis",
        hypothesis_profiles(snapshot.standards.get("python/conftest.py")),
        profiles,
    )


def level(value: object) -> str:
    if isinstance(value, str):
        return value
    setting = table(value).get("level")
    return setting if isinstance(setting, str) else ""


def rust_lint_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    for group in ("rust", "clippy"):
        key = f"lints.{group}"
        wanted, actual = table(standard.get(group)), table(project.get(group))
        for name, value in wanted.items():
            needed = RANKS.get(level(value))
            current = RANKS.get(level(actual.get(name)))
            if needed is not None and (current is None or current < needed):
                yield drift(
                    "Cargo.toml",
                    f"{key}.{name}",
                    f"{key}.{name} is weaker than `{level(value)}`",
                )
        yield from (
            drift("Cargo.toml", f"{key}.{name}", f"{key}.{name} relaxes a lint")
            for name, value in actual.items()
            if name not in wanted
            and (
                (rank := RANKS.get(level(value))) is None
                or rank < RANKS["deny"]
            )
        )


def disallowed(data: Mapping[str, object], key: str) -> FrozenList[str]:
    return FrozenList(
        path
        for entry in entries(data.get(key))
        if isinstance(path := table(entry).get("path"), str)
    )


def proptest_cases(config: Mapping[str, object]) -> int | None:
    value = lookup(config, "env.PROPTEST_CASES")
    value = table(value).get("value", value)
    return (
        int(value)
        if isinstance(value, str | int) and str(value).isdigit()
        else None
    )


def retries(value: object) -> bool:
    if is_list(value):
        return any(map(retries, value))
    data = table(value)
    return "retries" in data or any(map(retries, data.values()))


def rust_drift(snapshot: Snapshot) -> Iterator[Issue]:
    fragment = snapshot.standard_toml("rust/Cargo.fragment.toml")
    cargo = snapshot.toml("Cargo.toml")
    lints = table(cargo.get("lints")) or table(lookup(cargo, "workspace.lints"))
    if lints:
        yield from rust_lint_drift(table(fragment.get("lints")), lints)
    standard_clippy = snapshot.standard_toml("rust/clippy.toml")
    clippy = snapshot.toml("clippy.toml") or snapshot.toml(".clippy.toml")
    if clippy:
        for key in ("disallowed-types", "disallowed-methods"):
            yield from missing(
                "clippy.toml",
                key,
                disallowed(standard_clippy, key),
                disallowed(clippy, key),
            )
    yield from present(
        ".cargo/mutants.toml",
        snapshot.toml(".cargo/mutants.toml"),
        FrozenList((
            "exclude_globs",
            "exclude_re",
            "examine_globs",
            "examine_re",
        )),
        "mutants",
    )
    if retries(snapshot.toml(".config/nextest.toml")):
        yield drift(
            ".config/nextest.toml",
            "nextest.retries",
            "retries hide failing tests; list each flaky test in exceptions.toml",
        )
    cases = proptest_cases(snapshot.toml(".cargo/config.toml"))
    if cases is not None and cases < PROPTEST_CASES:
        yield drift(
            ".cargo/config.toml",
            "env.PROPTEST_CASES",
            f"PROPTEST_CASES is below {PROPTEST_CASES}",
        )


# Oxlint prints a finding's rule as `plugin(rule)`, but its resolved config
# names eslint's rules bare, a plugin with an underscore, and react's hooks
# rules under react, so drift names a rule as a finding prints it.
OXLINT_PLUGINS = FrozenOrderedDict({
    "jsx_a11y": "jsx-a11y",
    "react_perf": "react-perf",
})
HOOKS = FrozenOrderedSet(("rules-of-hooks", "exhaustive-deps"))
OXLINT_RANKS = FrozenOrderedDict({"allow": 0, "warn": 1, "deny": 2})
RESTRICTED = FrozenList(("no-restricted-globals", "no-restricted-imports"))
STANDARD_OXLINT = "#standards/oxlint"
# A project's oxlint.config.ts imports the standard's as `#standards/oxlint`,
# which check.sh maps to its copy, and names that import in `extends`.
STANDARD_IMPORT = re.compile(
    rf"""import\s+(\w+)\s+from\s+["']{STANDARD_OXLINT}["']"""
)
EXTENDS = re.compile(r"\bextends\s*:\s*\[([^\]]*)\]")


def printed(rule: str) -> str:
    plugin, slash, name = rule.rpartition("/")
    if not slash:
        return f"eslint/{rule}"
    if plugin == "react" and name in HOOKS:
        return f"react-hooks/{name}"
    return f"{OXLINT_PLUGINS.get(plugin, plugin)}/{name}"


def by_printed(rules: Mapping[str, object]) -> Mapping[str, object]:
    return FrozenOrderedDict(
        (printed(rule), value) for rule, value in rules.items()
    )


def oxlint_level(value: object) -> str:
    setting = next(iter(entries(value)), value)
    return setting if isinstance(setting, str) else "off"


def weaker(
    path: str,
    key: str,
    standard: Mapping[str, object],
    project: Mapping[str, object],
) -> Iterator[Issue]:
    for name, value in standard.items():
        wanted, actual = oxlint_level(value), oxlint_level(project.get(name))
        if OXLINT_RANKS.get(actual, 0) < OXLINT_RANKS.get(wanted, 0):
            label = f"{key}.{name}"
            yield drift(
                path, label, f"{label} is `{actual}`, weaker than `{wanted}`"
            )


def js_plugins(config: Mapping[str, object]) -> FrozenList[str]:
    return FrozenList(
        plugin
        if isinstance(plugin, str)
        else str(table(plugin).get("name", ""))
        for plugin in entries(config.get("jsPlugins"))
    )


def restricted(value: object) -> FrozenList[str]:
    return FrozenList(
        name
        for option in entries(value)[1:]
        for item in (option, *entries(table(option).get("paths")))
        if isinstance(
            name := item if isinstance(item, str) else table(item).get("name"),
            str,
        )
    )


def oxlint_overrides(
    config: Mapping[str, object],
) -> FrozenOrderedSet[tuple[str, str, str]]:
    return FrozenOrderedSet(
        (
            ",".join(strings(table(override).get("files"))),
            rule,
            oxlint_level(value),
        )
        for override in entries(config.get("overrides"))
        for rule, value in table(table(override).get("rules")).items()
    )


def extends_standard(source: str) -> bool:
    imported = STANDARD_IMPORT.search(source)
    return imported is not None and any(
        re.search(rf"\b{imported[1]}\b", found[1])
        for found in EXTENDS.finditer(source)
    )


def oxlint_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    path = "oxlint.config.ts"
    yield from weaker(
        path,
        "categories",
        table(standard.get("categories")),
        table(project.get("categories")),
    )
    wanted, actual = table(standard.get("rules")), table(project.get("rules"))
    yield from weaker(path, "rules", by_printed(wanted), by_printed(actual))
    yield from missing(
        path, "jsPlugins", js_plugins(standard), js_plugins(project)
    )
    for rule in RESTRICTED:
        yield from missing(
            path,
            f"rules.{printed(rule)}",
            restricted(wanted.get(rule)),
            restricted(actual.get(rule)),
        )
    standard_overrides = oxlint_overrides(standard)
    yield from (
        drift(
            path,
            f"overrides.{files}.{printed(rule)}",
            f"override for {files} sets {printed(rule)} to `{setting}`",
        )
        for files, rule, setting in oxlint_overrides(project)
        if (files, rule, setting) not in standard_overrides
        and OXLINT_RANKS.get(setting, 0)
        < OXLINT_RANKS.get(oxlint_level(wanted.get(rule)), 0)
    )
    options = table(project.get("options"))
    yield from (
        drift(
            path,
            f"options.{name}",
            f"options.{name} is `{json.dumps(options.get(name))}`, not `{json.dumps(value)}`",
        )
        for name, value in table(standard.get("options")).items()
        if options.get(name) != value
    )
    yield from extra(
        path,
        "ignorePatterns",
        strings(project.get("ignorePatterns")),
        strings(standard.get("ignorePatterns")),
    )


def typescript_oxlint_drift(snapshot: Snapshot) -> Iterator[Issue]:
    path = "oxlint.config.ts"
    source = snapshot.project.get(path)
    standard_path = f"typescript/{path}"
    if source is None:
        return
    if source != snapshot.standards.get(standard_path) and not extends_standard(
        source
    ):
        yield drift(
            path,
            "extends",
            f"{path} doesn't extend the standard's, imported from `{STANDARD_OXLINT}`",
        )
    project = parse_json(snapshot.resolved.get(path))
    if project:
        yield from oxlint_drift(
            parse_json(snapshot.resolved.get(standard_path)), project
        )


def vitest_runs(text: str | None) -> FrozenOrderedDict[str, int]:
    return FrozenOrderedDict(
        (match[1], int(match[2]))
        for match in MODE_RUNS.finditer(text if text is not None else "")
    )


def stryker_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    if not project:
        return
    path = "stryker.config.json"
    wanted, actual = (
        lookup(standard, "thresholds.break"),
        lookup(project, "thresholds.break"),
    )
    if isinstance(wanted, int) and not (
        isinstance(actual, int) and actual >= wanted
    ):
        yield drift(
            path, "thresholds.break", f"thresholds.break is below {wanted}"
        )
    yield from extra(
        path,
        "mutate",
        FrozenList(
            glob
            for glob in strings(project.get("mutate"))
            if glob.startswith("!")
        ),
        strings(standard.get("mutate")),
    )


def typescript_drift(snapshot: Snapshot) -> Iterator[Issue]:
    folder = "typescript/"
    yield from typescript_oxlint_drift(snapshot)
    compiler = "compilerOptions"
    options = table(snapshot.json("tsconfig.json").get(compiler))
    base = table(
        snapshot.standard_json(f"{folder}tsconfig.base.json").get(compiler)
    )
    switched_off = FrozenList(
        name
        for name, value in base.items()
        if value is True and options.get(name) is False
    )
    if options.get("strict") is False and "strict" not in switched_off:
        switched_off = FrozenList(("strict", *switched_off))
    yield from (
        drift(
            "tsconfig.json", f"{compiler}.{name}", f"{compiler}.{name} is false"
        )
        for name in switched_off
    )
    yield from stryker_drift(
        snapshot.standard_json(f"{folder}stryker.config.json"),
        snapshot.json("stryker.config.json"),
    )
    yield from intensity(
        "vitest.config.ts",
        "arbitrary",
        vitest_runs(snapshot.standards.get(f"{folder}vitest.config.ts")),
        vitest_runs(snapshot.project.get("vitest.config.ts")),
    )
    standard_knip = snapshot.standard_json(f"{folder}knip.json")
    knip = snapshot.json("knip.json") or snapshot.json("knip.jsonc")
    for key, value in knip.items():
        if key.startswith("ignore"):
            yield from extra(
                "knip.json",
                key,
                strings(value) or FrozenList((str(value),)),
                strings(standard_knip.get(key)),
            )


DRIFT = FrozenOrderedDict({
    "python": python_drift,
    "rust": rust_drift,
    "typescript": typescript_drift,
})
