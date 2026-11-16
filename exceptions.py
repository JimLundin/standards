import ast
import json
import re
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from itertools import starmap
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

EXCEPTIONS = Path("exceptions.toml")
FIELDS = frozenset({"path", "rule", "reason"})
WEAK = frozenset({
    "off",
    "none",
    "info",
    "information",
    "hint",
    "warn",
    "warning",
    "allow",
})
RANKS = MappingProxyType({
    "allow": 0,
    "warn": 1,
    "expect": 1,
    "deny": 2,
    "forbid": 3,
})
PROPTEST_CASES = 16
LIBRARY_KINDS = frozenset({"lib", "rlib"})
RUST_RULES = frozenset({"std", "api", "shell"})
IMMUTABILITY = re.compile(r"IMM\d{3}")
RUST_LINT = re.compile(r"(?:clippy::)?[a-z_]+")
PYTHON_MARKERS = (
    r"noqa\b",
    r"ruff\s*:",
    r"type\s*:\s*ignore",
    r"(?:based)?pyright\s*:",
    r"pragma\s*:\s*no\s+(?:mutate|cover)",
    r"fmt\s*:\s*(?:off|skip)",
    r"isort\s*:\s*skip",
)
TYPESCRIPT_MARKERS = (
    r"biome-ignore",
    r"@ts-(?:ignore|expect-error|nocheck)",
    r"Stryker\s+(?:disable|restore)",
    r"(?:c8|istanbul|node:coverage)\s+ignore",
    r"eslint-disable",
    r"prettier-ignore",
)
PYTHON_MARKER = re.compile(
    rf"#\s*(?:{'|'.join(PYTHON_MARKERS)})", re.IGNORECASE
)
TYPESCRIPT_MARKER = re.compile(
    rf"(?://|/\*)\s*(?:{'|'.join(TYPESCRIPT_MARKERS)})"
)
RUST_ATTRIBUTE = re.compile(
    r"#!?\[\s*(?P<name>[a-z_]+(?:::[a-z_]+)?)\s*(?P<args>\((?:[^()]|\([^()]*\))*\))?\s*\]"
)
REASON = re.compile(r'reason\s*=\s*"(?:[^"\\]|\\.)*"')
NUM_RUNS = re.compile(r"numRuns:\s*(\d+)")
INSTEAD = "; add an entry to exceptions.toml instead"


@dataclass(frozen=True, slots=True)
class Waiver:
    path: str
    rule: str
    reason: str

    def covers(self, path: str, rule: str) -> bool:
        return self.rule == rule and PurePosixPath(path).full_match(self.path)


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    message: str
    rule: str = ""


def table(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return cast("Mapping[str, object]", value)
    return MappingProxyType({})


def entries(value: object) -> tuple[object, ...]:
    if isinstance(value, list):
        return tuple(cast("Iterable[object]", value))
    return ()


def strings(value: object) -> tuple[str, ...]:
    return tuple(item for item in entries(value) if isinstance(item, str))


def lookup(data: Mapping[str, object], dotted: str) -> object:
    value: object = data
    for key in dotted.split("."):
        value = table(value).get(key)
    return value


def read_toml(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        return MappingProxyType({})
    return cast(
        "Mapping[str, object]", tomllib.loads(path.read_text(encoding="utf-8"))
    )


def read_json(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        return MappingProxyType({})
    try:
        return table(
            cast("object", json.loads(path.read_text(encoding="utf-8")))
        )
    except json.JSONDecodeError:
        return MappingProxyType({})


def parse_waiver(index: int, entry: object) -> Waiver | Issue:
    fields = table(entry)
    where = f"exception {index + 1}"
    unknown = sorted(set(fields) - FIELDS)
    if unknown:
        keys = ", ".join(unknown)
        return Issue(str(EXCEPTIONS), f"{where} has unknown keys: {keys}")
    values = tuple(fields.get(key) for key in ("path", "rule", "reason"))
    texts = tuple(value.strip() for value in values if isinstance(value, str))
    if len(texts) == len(values) and all(texts):
        path, rule, reason = texts
        return Waiver(path, rule, reason)
    return Issue(str(EXCEPTIONS), f"{where} needs a path, a rule and a reason")


def load() -> tuple[tuple[Waiver, ...], tuple[Issue, ...]]:
    try:
        data = read_toml(EXCEPTIONS)
    except tomllib.TOMLDecodeError as error:
        return (), (Issue(str(EXCEPTIONS), f"invalid TOML: {error}"),)
    parsed = tuple(
        starmap(parse_waiver, enumerate(entries(data.get("exception"))))
    )
    unknown = tuple(
        Issue(str(EXCEPTIONS), f"unknown table `{key}`")
        for key in data
        if key != "exception"
    )
    waivers = tuple(item for item in parsed if isinstance(item, Waiver))
    issues = tuple(item for item in parsed if isinstance(item, Issue))
    return waivers, (*issues, *unknown)


def kind(language: str, rule: str) -> str:
    if rule == "mutation" or (language == "rust" and rule in RUST_RULES):
        return rule
    if rule.startswith("drift:"):
        return "drift"
    if language == "python":
        return python_kind(rule)
    if language == "rust" and RUST_LINT.fullmatch(rule):
        return "attribute"
    if language == "typescript" and rule.startswith("lint/"):
        return "biome"
    return ""


def python_kind(rule: str) -> str:
    if IMMUTABILITY.fullmatch(rule):
        return "immutability"
    return "unused" if rule == "unused" else "ruff"


def waived(waivers: Iterable[Waiver], path: str, rule: str) -> bool:
    return any(waiver.covers(path, rule) for waiver in waivers)


def python_markers(path: Path) -> Iterator[tuple[int, str]]:
    try:
        with path.open("rb") as file:
            tokens = tuple(tokenize.tokenize(file.readline))
    except SyntaxError, tokenize.TokenError:
        return
    yield from (
        (token.start[0], token.string.strip())
        for token in tokens
        if token.type == tokenize.COMMENT and PYTHON_MARKER.search(token.string)
    )


def typescript_markers(path: Path) -> Iterator[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    yield from (
        (number, line.strip())
        for number, line in enumerate(lines, start=1)
        if TYPESCRIPT_MARKER.search(line)
    )


def attribute_lints(arguments: str) -> tuple[str, ...]:
    inner = REASON.sub("", arguments.strip()[1:-1])
    return tuple(part.strip() for part in inner.split(",") if part.strip())


def rust_attributes(path: Path) -> Iterator[tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8")
    for match in RUST_ATTRIBUTE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        yield line, match["name"], match["args"] or ""


def rust_issues(
    file: str, waivers: Iterable[Waiver]
) -> Iterator[tuple[Issue | None, str]]:
    for line, name, arguments in rust_attributes(Path(file)):
        where = f"{file}:{line}"
        if name == "expect":
            for lint in attribute_lints(arguments):
                registered = waived(waivers, file, lint)
                issue = Issue(
                    where, f"#[expect({lint})] is not in exceptions.toml"
                )
                yield (None if registered else issue), lint
        elif name in {"allow", "mutants::skip", "rustfmt::skip"} or (
            name == "cfg_attr"
            and re.search(r"\b(allow|expect|skip)\b", arguments)
        ):
            yield Issue(where, f"#[{name}{arguments}]{INSTEAD}"), ""


def suppressions(
    language: str, files: Iterable[str], waivers: Iterable[Waiver]
) -> Iterator[Issue]:
    markers = {"python": python_markers, "typescript": typescript_markers}
    scan = markers.get(language)
    for file in files:
        if scan is not None and is_source(language, file):
            yield from (
                Issue(f"{file}:{line}", f"suppression `{text}`{INSTEAD}")
                for line, text in scan(Path(file))
            )
        if language == "rust" and file.endswith(".rs"):
            yield from (
                issue
                for issue, _ in rust_issues(file, waivers)
                if issue is not None
            )


def is_source(language: str, file: str) -> bool:
    suffixes = {
        "python": (".py", ".pyw"),
        "typescript": (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs"),
    }
    return file.endswith(suffixes.get(language, ()))


def used_attributes(files: Iterable[str]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (file, lint)
        for file in files
        if file.endswith(".rs")
        for _, name, arguments in rust_attributes(Path(file))
        if name == "expect"
        for lint in attribute_lints(arguments)
    )


def waiver_issues(
    language: str, waivers: Iterable[Waiver], files: tuple[str, ...]
) -> Iterator[Issue]:
    attributes: frozenset[tuple[str, str]] = (
        used_attributes(files) if language == "rust" else frozenset()
    )
    for waiver in waivers:
        rule_kind = kind(language, waiver.rule)
        where = f"{EXCEPTIONS} ({waiver.path}, {waiver.rule})"
        matched = tuple(
            file
            for file in files
            if PurePosixPath(file).full_match(waiver.path)
        )
        if not rule_kind:
            yield Issue(where, f"unknown rule for {language}")
        elif rule_kind != "drift" and not matched:
            yield Issue(where, "path matches no tracked file")
        elif rule_kind == "std" and not any(
            PurePosixPath(file).name == "Cargo.toml" for file in matched
        ):
            yield Issue(where, "path matches no Cargo.toml")
        elif rule_kind == "attribute" and not any(
            (file, waiver.rule) in attributes for file in matched
        ):
            yield Issue(
                where, "no matching #[expect] attribute; remove the entry"
            )


def drift(path: str, key: str, problem: str) -> Issue:
    rule = f"drift:{key}"
    return Issue(path, f"{problem} (exception rule `{rule}`)", rule)


def missing(
    path: str, key: str, standard: Iterable[str], project: Iterable[str]
) -> Iterator[Issue]:
    present = frozenset(project)
    yield from (
        drift(path, f"{key}:{item}", f"{key} lacks `{item}`")
        for item in standard
        if item not in present
    )


def extra(
    path: str, key: str, project: Iterable[str], standard: Iterable[str]
) -> Iterator[Issue]:
    allowed = frozenset(standard)
    yield from (
        drift(path, f"{key}:{item}", f"{key} adds `{item}`")
        for item in project
        if item not in allowed
    )


def present(
    path: str, data: Mapping[str, object], keys: Iterable[str], prefix: str
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
        table(data.get("lint")) for data in (standard, project)
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
        tuple(table(lookup(standard_lint, banned))),
        tuple(table(lookup(project_lint, banned))),
    )
    hidden = ("extend-ignore", "extend-per-file-ignores", "exclude")
    yield from present(path, project_lint, hidden, key)
    yield from present(
        path, project, ("exclude", "extend-exclude"), "tool.ruff"
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
        if name not in standard and (value is False or value in WEAK)
    )
    yield from present(path, project, ("exclude", "ignore"), key)


def hypothesis_profiles(path: Path) -> Mapping[str, int]:
    if not path.is_file():
        return MappingProxyType({})
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return MappingProxyType({
        name.value: examples.value
        for node in ast.walk(tree)
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
    })


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


def python_drift(standards: Path, files: tuple[str, ...]) -> Iterator[Issue]:
    path = "pyproject.toml"
    standard = read_toml(standards / "python" / "pyproject.toml")
    project = read_toml(Path(path))
    for tool, check in (
        ("ruff", ruff_drift),
        ("basedpyright", basedpyright_drift),
    ):
        section = table(lookup(project, f"tool.{tool}"))
        if section:
            yield from check(table(lookup(standard, f"tool.{tool}")), section)
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
        ("do_not_mutate", "only_mutate", "do_not_mutate_patterns"),
        "tool.mutmut",
    )
    yield from missing(
        path,
        "tool.mutmut.pytest_add_cli_args",
        strings(lookup(standard, "tool.mutmut.pytest_add_cli_args")),
        strings(mutmut.get("pytest_add_cli_args")),
    )
    yield from import_drift(standard, project)
    conftests = tuple(file for file in files if file.endswith("conftest.py"))
    profiles = {
        name: value
        for file in conftests
        for name, value in hypothesis_profiles(Path(file)).items()
    }
    yield from intensity(
        conftests[0] if conftests else "tests/conftest.py",
        "hypothesis",
        hypothesis_profiles(standards / "python" / "conftest.py"),
        profiles,
    )


def forbidden(data: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        module
        for contract in entries(lookup(data, "tool.importlinter.contracts"))
        if table(contract).get("type") == "forbidden"
        for module in strings(table(contract).get("forbidden_modules"))
    )


def import_drift(
    standard: Mapping[str, object], project: Mapping[str, object]
) -> Iterator[Issue]:
    yield from missing(
        "pyproject.toml",
        "tool.importlinter.forbidden_modules",
        forbidden(standard),
        forbidden(project),
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


def disallowed(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    return tuple(
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


def rust_drift(standards: Path, _: tuple[str, ...]) -> Iterator[Issue]:
    fragment = read_toml(standards / "rust" / "Cargo.fragment.toml")
    cargo = read_toml(Path("Cargo.toml"))
    lints = table(cargo.get("lints")) or table(lookup(cargo, "workspace.lints"))
    if lints:
        yield from rust_lint_drift(table(fragment.get("lints")), lints)
    standard_clippy = read_toml(standards / "rust" / "clippy.toml")
    clippy = read_toml(Path("clippy.toml")) or read_toml(Path(".clippy.toml"))
    if clippy:
        for key in ("disallowed-types", "disallowed-methods"):
            yield from missing(
                "clippy.toml",
                key,
                disallowed(standard_clippy, key),
                disallowed(clippy, key),
            )
    mutants = read_toml(Path(".cargo/mutants.toml"))
    yield from present(
        ".cargo/mutants.toml",
        mutants,
        ("exclude_globs", "exclude_re", "examine_globs", "examine_re"),
        "mutants",
    )
    cases = proptest_cases(read_toml(Path(".cargo/config.toml")))
    if cases is not None and cases < PROPTEST_CASES:
        yield drift(
            ".cargo/config.toml",
            "env.PROPTEST_CASES",
            f"PROPTEST_CASES is below {PROPTEST_CASES}",
        )


def biome_levels(rules: Mapping[str, object]) -> Mapping[str, str]:
    flat: dict[str, str] = {}
    for group, value in rules.items():
        if isinstance(value, str):
            flat[group] = value
        for rule, setting in table(value).items():
            flat[f"{group}/{rule}"] = level(setting)
    return MappingProxyType(flat)


def biome_options(
    rules: Mapping[str, object], rule: str, key: str
) -> tuple[str, ...]:
    group, name = rule.split("/")
    options = table(table(table(rules.get(group)).get(name)).get("options"))
    return tuple(table(options.get(key)))


def overrides(config: Mapping[str, object]) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (",".join(strings(table(override).get("includes"))), rule, setting)
        for override in entries(config.get("overrides"))
        for rule, setting in biome_levels(
            table(lookup(table(override), "linter.rules"))
        ).items()
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
        (Path(plugin).name for plugin in plugin_paths(standard)),
        (Path(plugin).name for plugin in plugin_paths(project)),
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


def plugin_paths(config: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        plugin
        if isinstance(plugin, str)
        else str(table(plugin).get("path", ""))
        for plugin in entries(config.get("plugins"))
    )


def typescript_drift(standards: Path, _: tuple[str, ...]) -> Iterator[Issue]:
    folder = standards / "typescript"
    project = read_json(Path("biome.json")) or read_json(Path("biome.jsonc"))
    if project:
        yield from biome_drift(read_json(folder / "biome.json"), project)
    compiler = "compilerOptions"
    options = table(read_json(Path("tsconfig.json")).get(compiler))
    yield from (
        drift(
            "tsconfig.json", f"{compiler}.{name}", f"{compiler}.{name} is false"
        )
        for name, value in table(
            read_json(folder / "tsconfig.base.json").get(compiler)
        ).items()
        if value is True and options.get(name) is False
    )
    if options.get("strict") is False:
        yield drift(
            "tsconfig.json", f"{compiler}.strict", f"{compiler}.strict is false"
        )
    yield from stryker_drift(
        read_json(folder / "stryker.config.json"),
        read_json(Path("stryker.config.json")),
    )
    standard_runs = {
        name: runs(folder / "profiles" / f"{name}.ts")
        for name in ("fast", "full", "mutation")
    }
    yield from intensity(
        "profiles",
        "fast-check",
        {
            name: value
            for name, value in standard_runs.items()
            if value is not None
        },
        {
            name: value
            for name in standard_runs
            if (value := runs(Path("profiles") / f"{name}.ts")) is not None
        },
    )
    standard_knip = read_json(folder / "knip.json")
    knip = read_json(Path("knip.json")) or read_json(Path("knip.jsonc"))
    for key, value in knip.items():
        if key.startswith("ignore"):
            yield from extra(
                "knip.json",
                key,
                strings(value) or (str(value),),
                strings(standard_knip.get(key)),
            )


def runs(path: Path) -> int | None:
    if not path.is_file():
        return None
    match = NUM_RUNS.search(path.read_text(encoding="utf-8"))
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
        (
            glob
            for glob in strings(project.get("mutate"))
            if glob.startswith("!")
        ),
        strings(standard.get("mutate")),
    )


DRIFT = MappingProxyType({
    "python": python_drift,
    "rust": rust_drift,
    "typescript": typescript_drift,
})


def check(
    language: str, standards: Path, files: tuple[str, ...]
) -> tuple[Issue, ...]:
    waivers, problems = load()
    drifted = tuple(
        issue
        for issue in DRIFT[language](standards, files)
        if not waived(waivers, issue.path, issue.rule)
    )
    return (
        *problems,
        *waiver_issues(language, waivers, files),
        *suppressions(language, files, waivers),
        *drifted,
    )


def ruff_config() -> str:
    waivers, _ = load()
    rules: dict[str, tuple[str, ...]] = {}
    for waiver in waivers:
        if kind("python", waiver.rule) == "ruff":
            rules[waiver.path] = (*rules.get(waiver.path, ()), waiver.rule)
    if not rules:
        return ""
    pairs = ", ".join(
        f"{json.dumps(path)} = {json.dumps(list(names))}"
        for path, names in rules.items()
    )
    return f"lint.extend-per-file-ignores = {{{pairs}}}"


def immutability_args() -> tuple[str, ...]:
    waivers, _ = load()
    return tuple(
        f"--skip={waiver.rule}:{waiver.path}"
        for waiver in waivers
        if kind("python", waiver.rule) == "immutability"
    )


def without(rule: str, files: Iterable[str]) -> tuple[str, ...]:
    waivers, _ = load()
    return tuple(file for file in files if not waived(waivers, file, rule))


def globs(rule: str) -> tuple[str, ...]:
    waivers, _ = load()
    return tuple(waiver.path for waiver in waivers if waiver.rule == rule)


def biome_groups(files: Iterable[str]) -> tuple[str, ...]:
    waivers, _ = load()
    groups: dict[tuple[str, ...], tuple[str, ...]] = {}
    for file in files:
        skips = tuple(
            sorted(
                waiver.rule.removeprefix("lint/")
                for waiver in waivers
                if waiver.rule.startswith("lint/")
                and not waiver.rule.startswith("lint/plugin/")
                and waiver.covers(file, waiver.rule)
            )
        )
        groups[skips] = (*groups.get(skips, ()), file)
    return tuple(
        "|".join((" ".join(skips), *members))
        for skips, members in groups.items()
    )


def biome_plugins(config: Path) -> tuple[str, ...]:
    folder = config.parent.resolve()
    return tuple(
        f"{Path(plugin).stem}|{(folder / plugin).resolve().as_posix()}"
        for plugin in plugin_paths(read_json(config))
    )


def module_files(module: str) -> tuple[str, ...]:
    base = module.replace(".", "/")
    return tuple(
        f"{root}{base}{suffix}"
        for root in ("src/", "")
        for suffix in (".py", "/__init__.py")
    )


def filter_mutmut(lines: Iterable[str]) -> tuple[str, ...]:
    waivers, _ = load()
    return tuple(
        line
        for line in lines
        if not any(
            waived(waivers, file, "mutation")
            for file in module_files(
                line.strip().split(":")[0].rsplit(".", 1)[0]
            )
        )
    )


def stryker_mutate(config: Path) -> str:
    return ",".join((
        *strings(read_json(config).get("mutate")),
        *(f"!{glob}" for glob in globs("mutation")),
    ))


def target_kinds(package: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        kind
        for target in entries(package.get("targets"))
        for kind in strings(table(target).get("kind"))
    )


def manifest(root: str, package: Mapping[str, object]) -> str:
    path = Path(str(package.get("manifest_path", "")))
    return path.relative_to(root).as_posix()


def core_libraries(
    metadata: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[Issue, ...]]:
    waivers, _ = load()
    root = str(metadata.get("workspace_root", ""))
    packages = tuple(table(item) for item in entries(metadata.get("packages")))
    libraries = tuple(
        str(package.get("name"))
        for package in packages
        if target_kinds(package) & LIBRARY_KINDS
        and not waived(waivers, manifest(root, package), "std")
    )
    binaries = any("bin" in target_kinds(package) for package in packages)
    if binaries and not libraries and not waived(waivers, "Cargo.toml", "std"):
        message = "has binaries but no no_std library to hold the pure core"
        return (), (Issue("Cargo.toml", message),)
    return libraries, ()


def report(issues: Iterable[Issue]) -> int:
    lines = tuple(f"{issue.path}: {issue.message}" for issue in issues)
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    write((*lines, summary))
    return 1 if lines else 0


def write(lines: Iterable[str]) -> None:
    text = "".join(f"{line}\n" for line in lines if line)
    _ = sys.stdout.buffer.write(text.encode())


def main(arguments: tuple[str, ...]) -> int:
    command, *rest = arguments
    if command == "check":
        return report(check(rest[0], Path(rest[1]), tuple(rest[2:])))
    if command == "core-libraries":
        libraries, issues = core_libraries(read_json(Path(rest[0])))
        write((
            *libraries,
            *(f"{issue.path}: {issue.message}" for issue in issues),
        ))
        return 1 if issues else 0
    outputs = {
        "ruff-config": lambda: (ruff_config(),),
        "immutability-args": immutability_args,
        "without": lambda: without(rest[0], rest[1:]),
        "globs": lambda: globs(rest[0]),
        "biome-groups": lambda: biome_groups(rest),
        "biome-plugins": lambda: biome_plugins(Path(rest[0])),
        "filter-mutmut": lambda: filter_mutmut(sys.stdin.read().splitlines()),
        "stryker-mutate": lambda: (stryker_mutate(Path(rest[0])),),
    }
    write(outputs[command]())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))
