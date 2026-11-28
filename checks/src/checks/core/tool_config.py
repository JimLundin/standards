import ast
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from ordered import FrozenList, FrozenOrderedDict

from checks.core.exceptions import (
    EXCEPTIONS,
    FLAKY,
    MUTATION,
    UNUSED,
    ExceptionEntry,
    exceptions_in,
    kind,
    named,
    oxlint_rule,
)
from checks.core.sides import SIDES, side_of, tests_of
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    absolute,
    listing,
    matches,
    operands,
    option,
    parse_json,
    posix,
    strings,
    table,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


TEST_IGNORES = FrozenList((
    "assert",
    "implicit-namespace-package",
    "magic-value-comparison",
))


def ruff_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    rules: FrozenOrderedDict[str, FrozenList[str]] = FrozenOrderedDict(
        (glob, TEST_IGNORES) for glob in tests_of("python")
    )
    for entry in exceptions_in(inputs).entries:
        if kind("python", entry.rule) == "ruff":
            known = rules.get(entry.path, FrozenList())
            rules |= {entry.path: FrozenList((*known, entry.rule))}
    pairs = ", ".join(
        f"{json.dumps(path)} = {json.dumps(list(names))}"
        for path, names in rules.items()
    )
    return listing((f"lint.extend-per-file-ignores = {{{pairs}}}",))


def globs(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(exceptions_in(inputs).paths(arguments[0]))


OXLINT_CONFIG = "node_modules/.cache/standards/oxlint.config.mjs"


def oxlint_override(project_root: str, entry: ExceptionEntry) -> str:
    rule = oxlint_rule(entry.rule)
    if not rule:
        return ""
    files, key = json.dumps([f"{project_root}/{entry.path}"]), json.dumps(rule)

    return f'\t\t{{ files: {files}, rules: {{ {key}: "off" }} }},\n'


def file_url(path: str) -> str:
    drive, rest = (
        ("", path) if path.startswith("/") else (f"/{path[:2]}", path[2:])
    )
    return f"file://{drive}{quote(rest)}"


def oxlint_config(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    *flags, path = arguments
    root = posix(inputs.cwd)
    config = json.dumps(file_url(absolute(path, inputs.cwd)))
    options = (
        "\toptions: { ...config.options, typeAware: false },\n"
        if "--untyped" in flags
        else ""
    )
    overrides = "".join(
        oxlint_override(root, entry) for entry in exceptions_in(inputs).entries
    )
    text = (
        f"import config from {config};\n\n"
        "export default {\n"
        "\textends: [config],\n"
        f"{options}"
        f"\toverrides: [\n{overrides}\t],\n"
        "};\n"
    )
    return Outcome(
        FrozenList((OXLINT_CONFIG,)),
        writes=FrozenOrderedDict({OXLINT_CONFIG: text}),
    )


def module_files(module: str) -> FrozenList[str]:
    base = module.replace(".", "/")
    return FrozenList(
        f"{root}{base}{suffix}"
        for root in ("src/", "")
        for suffix in (".py", "/__init__.py")
    )


def filter_mutmut(_: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    return listing(
        FrozenList(
            line
            for line in inputs.stdin.splitlines()
            if not any(
                exceptions.covers(MUTATION, file)
                for file in module_files(line.strip().rsplit(".", 1)[0])
            )
        )
    )


@dataclass(frozen=True, slots=True)
class Scope:
    name: str
    start: int
    header: int
    end: int


def scopes(text: str) -> FrozenList[Scope]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return FrozenList()
    return FrozenList(
        Scope(
            node.name,
            min(
                (decorator.lineno for decorator in node.decorator_list),
                default=node.lineno,
            ),
            node.lineno,
            node.end_lineno or node.lineno,
        )
        for node in ast.walk(tree)
        if isinstance(
            node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        )
    )


def qualified(found: Sequence[Scope], line: int, name: str) -> str:
    enclosing = sorted(
        (
            scope
            for scope in found
            if scope.start <= line <= scope.end
            and not (scope.name == name and line <= scope.header)
        ),
        key=lambda scope: scope.start,
    )
    return ".".join((*(scope.name for scope in enclosing), name))


@dataclass(frozen=True, slots=True)
class Finding:
    line: str
    file: str
    item: str


def finding_of(line: str, texts: Mapping[str, str]) -> Finding:
    file, _, rest = line.partition(":")
    number, _, message = rest.partition(":")
    name = message.partition("'")[2].partition("'")[0]
    path = posix(file)
    text = texts.get(path)
    if text is None or not number.isdigit():
        return Finding(line, path, name)
    return Finding(line, path, qualified(scopes(text), int(number), name))


def drops(entry: ExceptionEntry, finding: Finding) -> bool:
    return entry.covers(UNUSED, finding.file) and (
        not entry.names or finding.item in entry.names
    )


def bound(node: ast.AST) -> tuple[int, str] | None:
    match node:
        case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
            return node.lineno, node.name
        case ast.Name(ctx=ast.Store()):
            return node.lineno, node.id
        case ast.Attribute(ctx=ast.Store()):
            return node.lineno, node.attr
        case ast.alias():
            return node.lineno, (node.asname or node.name).partition(".")[0]
        case ast.arg():
            return node.lineno, node.arg
        case _:
            return None


def items(text: str) -> FrozenList[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return FrozenList()
    found = scopes(text)
    return FrozenList(
        qualified(found, *binding)
        for node in ast.walk(tree)
        if (binding := bound(node))
    )


def stale(
    entry: ExceptionEntry,
    findings: Sequence[Finding],
    arguments: Sequence[str],
    texts: Mapping[str, str],
) -> FrozenList[str]:
    side = SIDES.get(option(arguments, "--side="))
    covered = FrozenList(
        path
        for file in operands(arguments)
        if matches(path := posix(file), entry.path)
    )
    here = FrozenList(path for path in covered if side_of(path) == side)
    if not here:
        return FrozenList()
    defined_here = FrozenList(
        item for path in here for item in items(text(texts, path))
    )
    defined = FrozenList(
        item for path in covered for item in items(text(texts, path))
    )
    return FrozenList(
        (
            f"{EXCEPTIONS} ({entry.path}): unused name `{name}` matches no"
            " finding; fix: remove it from `names`"
        )
        for name in entry.names
        if (name in defined_here or name not in defined)
        and not any(
            finding.item == name and matches(finding.file, entry.path)
            for finding in findings
        )
    )


def filter_vulture(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    entries = exceptions_in(inputs).entries
    findings = FrozenList(
        finding_of(line, inputs.texts) for line in inputs.stdin.splitlines()
    )
    kept = FrozenList(
        finding.line
        for finding in findings
        if not any(drops(entry, finding) for entry in entries)
    )
    return listing(
        kept
        + FrozenList(
            line
            for entry in named(entries)
            for line in stale(entry, findings, arguments, inputs.texts)
        )
    )


def filter_vulture_request(arguments: Sequence[str], inputs: Inputs) -> Request:
    entries = named(exceptions_in(inputs).entries)
    covered = FrozenList(
        file
        for file in operands(arguments)
        if any(matches(posix(file), entry.path) for entry in entries)
    )
    return Request(FrozenList((EXCEPTIONS, *covered)), stdin=True)


@dataclass(frozen=True, slots=True)
class StrykerConfig:
    fields: Mapping[str, object]
    mutate: FrozenList[str]
    vitest: Mapping[str, object]


def stryker_config_of(text: str | None) -> StrykerConfig:
    fields = parse_json(text)
    return StrykerConfig(
        fields, strings(fields.get("mutate")), table(fields.get("vitest"))
    )


def stryker_mutate(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    excepted = exceptions_in(inputs).paths(MUTATION)
    if not excepted:
        return Outcome()
    config = stryker_config_of(inputs.texts.get(arguments[0]))
    return listing((
        ",".join((*config.mutate, *(f"!{glob}" for glob in excepted))),
    ))


STRYKER_CONFIG = "node_modules/.cache/standards/stryker.config.json"


def stryker_config(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    path, vitest_config = arguments
    config = stryker_config_of(inputs.texts.get(path))
    copy = {
        **config.fields,
        "vitest": {**config.vitest, "configFile": vitest_config},
    }
    return Outcome(
        FrozenList((STRYKER_CONFIG,)),
        writes=FrozenOrderedDict({STRYKER_CONFIG: json.dumps(copy)}),
    )


def nextest_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            line
            for glob in exceptions_in(inputs).paths(FLAKY)
            for line in (
                "[[profile.default.overrides]]",
                f"filter = {json.dumps(f'test(#{glob})')}",
                "retries = 1",
            )
        )
    )


def exceptions_only(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)))


def with_named(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, arguments[0])))


def with_stdin(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)), stdin=True)


type Step[T] = Callable[[Sequence[str], Inputs], T]

COMMANDS: FrozenOrderedDict[str, tuple[Step[Request], Step[Outcome]]] = (
    FrozenOrderedDict({
        "ruff-config": (exceptions_only, ruff_config),
        "globs": (exceptions_only, globs),
        "oxlint-config": (exceptions_only, oxlint_config),
        "filter-mutmut": (with_stdin, filter_mutmut),
        "filter-vulture": (filter_vulture_request, filter_vulture),
        "stryker-mutate": (with_named, stryker_mutate),
        "stryker-config": (with_named, stryker_config),
        "nextest-config": (exceptions_only, nextest_config),
    })
)
