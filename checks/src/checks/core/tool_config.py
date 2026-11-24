import json
from typing import TYPE_CHECKING
from urllib.parse import quote

from ordered import FrozenList, FrozenOrderedDict

from checks.core import typescript_layers
from checks.core.exceptions import (
    EXCEPTIONS,
    FLAKY,
    MUTATION,
    OXLINT,
    ExceptionEntry,
    exceptions_in,
    kind,
)
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    absolute,
    listing,
    operands,
    option,
    parse_json,
    posix,
    strings,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def ruff_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    rules: FrozenOrderedDict[str, FrozenList[str]] = FrozenOrderedDict()
    for entry in exceptions_in(inputs).entries:
        if kind("python", entry.rule) == "ruff":
            known = rules.get(entry.path, FrozenList())
            rules |= {entry.path: FrozenList((*known, entry.rule))}
    if not rules:
        return Outcome()
    pairs = ", ".join(
        f"{json.dumps(path)} = {json.dumps(list(names))}"
        for path, names in rules.items()
    )
    return listing((f"lint.extend-per-file-ignores = {{{pairs}}}",))


def without(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    rule, *files = arguments
    exceptions = exceptions_in(inputs)
    return listing(
        FrozenList(file for file in files if not exceptions.covers(rule, file))
    )


def globs(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(exceptions_in(inputs).paths(arguments[0]))


OXLINT_CONFIG = "node_modules/.cache/standards/oxlint.config.mjs"


def oxlint_override(root: str, entry: ExceptionEntry) -> str:
    found = OXLINT.fullmatch(entry.rule)
    if not found:
        return ""
    files = json.dumps([f"{root}/{entry.path}"])
    rule = json.dumps(f"{found[1]}/{found[2]}")
    return f'\t\t{{ files: {files}, rules: {{ {rule}: "off" }} }},\n'


# A file URL of an absolute path, which Node imports on any platform, such as
# file:///C:/work/a.ts for a Windows path.
def file_url(path: str) -> str:
    drive = "" if path.startswith("/") else f"/{path[:2]}"
    return f"file://{drive}{quote(path.removeprefix(drive[1:]))}"


# Oxlint resolves an override's globs against its config's folder, which
# here is not the project root, and matches a file outside that folder by
# its absolute path, so each glob is anchored at the project root. The
# exceptions come last, so that one turning a rule off wins. Untyped, for a
# project without a tsconfig.json, the type-aware rules are off. An override
# that adds to a restricting rule's options reads them with `restricted`,
# from the config, or from the standard's (`--standard`, which defaults to
# the config) where the config is a project's that leaves them to it.
def oxlint_config(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    path, *files = operands(arguments)
    root = posix(inputs.cwd)
    config = json.dumps(file_url(absolute(path, inputs.cwd)))
    standard = json.dumps(
        file_url(absolute(option(arguments, "--standard=") or path, inputs.cwd))
    )
    options = (
        "\toptions: { ...config.options, typeAware: false },\n"
        if "--untyped" in arguments
        else ""
    )
    exceptions = exceptions_in(inputs)
    placed = typescript_layers.placements(files, inputs.texts)
    if issues := typescript_layers.layer_issues(placed):
        return Outcome(issues, 1)
    overrides = typescript_layers.import_overrides(
        root, placed, exceptions
    ) + "".join(oxlint_override(root, entry) for entry in exceptions.entries)
    text = (
        f"import config from {config};\n"
        f"import standard from {standard};\n\n"
        "const restricted = (rule) =>\n"
        "\t(config.rules?.[rule] ?? standard.rules[rule]).slice(1);\n\n"
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


def stryker_mutate(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    """Stryker's mutate globs without the files of mutation exceptions and,
    from the file the second argument names, the shell's files."""
    excepted = (
        *exceptions_in(inputs).paths(MUTATION),
        *(
            inputs.texts.get(arguments[1], "").splitlines()
            if len(arguments) > 1
            else ()
        ),
    )
    if not excepted:
        return Outcome()
    config = parse_json(inputs.texts.get(arguments[0]))
    return listing((
        ",".join((
            *strings(config.get("mutate")),
            *(f"!{glob}" for glob in excepted),
        )),
    ))


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


def with_manifests(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(
        FrozenList((
            EXCEPTIONS,
            *typescript_layers.manifests(operands(arguments)[1:]),
        ))
    )


def with_named(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, *operands(arguments))))


def with_stdin(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)), stdin=True)


type Step[T] = Callable[[Sequence[str], Inputs], T]

COMMANDS: FrozenOrderedDict[str, tuple[Step[Request], Step[Outcome]]] = (
    FrozenOrderedDict({
        "ruff-config": (exceptions_only, ruff_config),
        "without": (exceptions_only, without),
        "globs": (exceptions_only, globs),
        "oxlint-config": (with_manifests, oxlint_config),
        "filter-mutmut": (with_stdin, filter_mutmut),
        "stryker-mutate": (with_named, stryker_mutate),
        "nextest-config": (exceptions_only, nextest_config),
    })
)
