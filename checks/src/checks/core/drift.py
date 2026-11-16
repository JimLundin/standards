import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.values import (
    entries,
    lookup,
    parse_json,
    parse_toml,
    strings,
    table,
)
from checks.core.waivers import Issue

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
NUM_RUNS = re.compile(r"numRuns:\s*(\d+)")
PROFILES = FrozenList(("fast", "full", "mutation"))
PROJECT_FILES = FrozenOrderedDict({
    "python": FrozenList(("pyproject.toml",)),
    "rust": FrozenList((
        "Cargo.toml",
        "clippy.toml",
        ".clippy.toml",
        ".cargo/mutants.toml",
        ".cargo/config.toml",
    )),
    "typescript": FrozenList((
        "biome.json",
        "biome.jsonc",
        "tsconfig.json",
        "stryker.config.json",
        "knip.json",
        "knip.jsonc",
        *(f"profiles/{name}.ts" for name in PROFILES),
    )),
})
STANDARD_FILES = FrozenOrderedDict({
    "python": FrozenList(("python/pyproject.toml", "python/conftest.py")),
    "rust": FrozenList(("rust/Cargo.fragment.toml", "rust/clippy.toml")),
    "typescript": FrozenList((
        "typescript/biome.json",
        "typescript/tsconfig.base.json",
        "typescript/stryker.config.json",
        "typescript/knip.json",
        *(f"typescript/profiles/{name}.ts" for name in PROFILES),
    )),
})


@dataclass(frozen=True, slots=True)
class Snapshot:
    files: FrozenList[str]
    project: FrozenOrderedDict[str, str]
    standards: FrozenOrderedDict[str, str]

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
            if RANKS.get(level(actual.get(name)), -1) < RANKS.get(
                level(value), 0
            ):
                yield drift(
                    "Cargo.toml",
                    f"{key}.{name}",
                    f"{key}.{name} is weaker than `{level(value)}`",
                )
        yield from (
            drift("Cargo.toml", f"{key}.{name}", f"{key}.{name} relaxes a lint")
            for name, value in actual.items()
            if name not in wanted and RANKS.get(level(value), 0) < RANKS["deny"]
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
    cases = proptest_cases(snapshot.toml(".cargo/config.toml"))
    if cases is not None and cases < PROPTEST_CASES:
        yield drift(
            ".cargo/config.toml",
            "env.PROPTEST_CASES",
            f"PROPTEST_CASES is below {PROPTEST_CASES}",
        )


def biome_levels(rules: Mapping[str, object]) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        pair
        for group, value in rules.items()
        for pair in (
            ((group, value),)
            if isinstance(value, str)
            else (
                (f"{group}/{rule}", level(setting))
                for rule, setting in table(value).items()
            )
        )
    )


def biome_options(
    rules: Mapping[str, object], rule: str, key: str
) -> FrozenList[str]:
    group, name = rule.split("/")
    options = table(table(table(rules.get(group)).get(name)).get("options"))
    return FrozenList(table(options.get(key)))


def overrides(
    config: Mapping[str, object],
) -> FrozenOrderedSet[tuple[str, str, str]]:
    return FrozenOrderedSet(
        (",".join(strings(table(override).get("includes"))), rule, setting)
        for override in entries(config.get("overrides"))
        for rule, setting in biome_levels(
            table(lookup(table(override), "linter.rules"))
        ).items()
    )


def plugin_paths(config: Mapping[str, object]) -> FrozenList[str]:
    return FrozenList(
        plugin
        if isinstance(plugin, str)
        else str(table(plugin).get("path", ""))
        for plugin in entries(config.get("plugins"))
    )


def biome_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    path = "biome.json"
    rules_key = "linter.rules"
    wanted, actual = (
        table(lookup(standard, rules_key)),
        table(lookup(project, rules_key)),
    )
    if actual.get("preset") != wanted.get("preset"):
        yield drift(
            path,
            f"{rules_key}.preset",
            f"{rules_key}.preset is not `{wanted.get('preset')}`",
        )
    if lookup(project, "linter.enabled") is False:
        yield drift(path, "linter.enabled", "the linter is disabled")
    yield from missing(
        path,
        "plugins",
        FrozenList(
            PurePosixPath(plugin).name for plugin in plugin_paths(standard)
        ),
        FrozenList(
            PurePosixPath(plugin).name for plugin in plugin_paths(project)
        ),
    )
    standard_levels = biome_levels(wanted)
    yield from (
        drift(path, f"{rules_key}.{rule}", f"{rules_key}.{rule} is `{setting}`")
        for rule, setting in biome_levels(actual).items()
        if setting in WEAK and standard_levels.get(rule) != setting
    )
    for rule, key in (
        ("style/noRestrictedGlobals", "deniedGlobals"),
        ("style/noRestrictedImports", "paths"),
    ):
        yield from missing(
            path,
            f"{rules_key}.{rule}.{key}",
            biome_options(wanted, rule, key),
            biome_options(actual, rule, key),
        )
    standard_overrides = overrides(standard)
    yield from (
        drift(
            path,
            f"overrides.{includes}.{rule}",
            f"override for {includes} sets {rule} to `{setting}`",
        )
        for includes, rule, setting in overrides(project)
        if setting in WEAK
        and (includes, rule, setting) not in standard_overrides
    )


def runs(text: str | None) -> int | None:
    match = NUM_RUNS.search(text or "")
    return int(match[1]) if match else None


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


def counts(
    texts: Mapping[str, str], folder: str
) -> FrozenOrderedDict[str, int]:
    return FrozenOrderedDict(
        (name, value)
        for name in PROFILES
        if (value := runs(texts.get(f"{folder}profiles/{name}.ts"))) is not None
    )


def typescript_drift(snapshot: Snapshot) -> Iterator[Issue]:
    folder = "typescript/"
    project = snapshot.json("biome.json") or snapshot.json("biome.jsonc")
    if project:
        yield from biome_drift(
            snapshot.standard_json(f"{folder}biome.json"), project
        )
    compiler = "compilerOptions"
    options = table(snapshot.json("tsconfig.json").get(compiler))
    yield from (
        drift(
            "tsconfig.json", f"{compiler}.{name}", f"{compiler}.{name} is false"
        )
        for name, value in table(
            snapshot.standard_json(f"{folder}tsconfig.base.json").get(compiler)
        ).items()
        if value is True and options.get(name) is False
    )
    if options.get("strict") is False:
        yield drift(
            "tsconfig.json", f"{compiler}.strict", f"{compiler}.strict is false"
        )
    yield from stryker_drift(
        snapshot.standard_json(f"{folder}stryker.config.json"),
        snapshot.json("stryker.config.json"),
    )
    yield from intensity(
        "profiles",
        "fast-check",
        counts(snapshot.standards, folder),
        counts(snapshot.project, ""),
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
