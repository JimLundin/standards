import json
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

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


# Oxlint resolves an override's globs against its config's folder, which
# here is not the project root, and matches a file outside that folder by
# its absolute path, so each glob is anchored at the project root.
def oxlint_config(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    root = posix(inputs.cwd)
    config = json.dumps(absolute(arguments[0], inputs.cwd))
    overrides = "".join(
        oxlint_override(root, entry) for entry in exceptions_in(inputs).entries
    )
    text = (
        'import { pathToFileURL } from "node:url";\n\n'
        "const { default: config } = await import("
        f"pathToFileURL({config}).href);\n\n"
        "export default {\n"
        "\textends: [config],\n"
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
    excepted = exceptions_in(inputs).paths(MUTATION)
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


def with_named(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, arguments[0])))


def with_stdin(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)), stdin=True)


type Step[T] = Callable[[Sequence[str], Inputs], T]

COMMANDS: FrozenOrderedDict[str, tuple[Step[Request], Step[Outcome]]] = (
    FrozenOrderedDict({
        "ruff-config": (exceptions_only, ruff_config),
        "without": (exceptions_only, without),
        "globs": (exceptions_only, globs),
        "oxlint-config": (exceptions_only, oxlint_config),
        "filter-mutmut": (with_stdin, filter_mutmut),
        "stryker-mutate": (with_named, stryker_mutate),
        "nextest-config": (exceptions_only, nextest_config),
    })
)
