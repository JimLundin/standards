import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import plugin_paths
from checks.core.exceptions import (
    EXCEPTIONS,
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
    normalized,
    parse_json,
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


def globs_of(rule: str, entries: Sequence[ExceptionEntry]) -> FrozenList[str]:
    return FrozenList(entry.path for entry in entries if entry.rule == rule)


def globs(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(globs_of(arguments[0], exceptions_in(inputs).entries))


def biome_skips(
    file: str, entries: Sequence[ExceptionEntry]
) -> FrozenList[str]:
    return FrozenList(
        sorted(
            entry.rule.removeprefix("lint/")
            for entry in entries
            if entry.rule.startswith("lint/")
            and not entry.rule.startswith("lint/plugin/")
            and entry.covers(entry.rule, file)
        )
    )


def biome_groups(files: Sequence[str], inputs: Inputs) -> Outcome:
    entries = exceptions_in(inputs).entries
    groups: FrozenOrderedDict[FrozenList[str], FrozenList[str]] = (
        FrozenOrderedDict()
    )
    for file in files:
        skips = biome_skips(file, entries)
        known = groups.get(skips, FrozenList())
        groups |= {skips: FrozenList((*known, file))}
    return listing(
        FrozenList(
            "|".join((" ".join(skips), *members))
            for skips, members in groups.items()
        )
    )


def biome_plugins(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    folder = PurePosixPath(absolute(arguments[0], inputs.cwd)).parent
    return listing(
        FrozenList(
            f"{PurePosixPath(plugin).stem}|{normalized(f'{folder}/{plugin}')}"
            for plugin in plugin_paths(
                parse_json(inputs.texts.get(arguments[0]))
            )
        )
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
                exceptions.covers("mutation", file)
                for file in module_files(line.strip().rsplit(".", 1)[0])
            )
        )
    )


def stryker_mutate(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    config = parse_json(inputs.texts.get(arguments[0]))
    return listing((
        ",".join((
            *strings(config.get("mutate")),
            *(
                f"!{glob}"
                for glob in globs_of("mutation", exceptions_in(inputs).entries)
            ),
        )),
    ))


def nextest_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            line
            for glob in globs_of("flaky", exceptions_in(inputs).entries)
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
        "biome-groups": (exceptions_only, biome_groups),
        "biome-plugins": (with_named, biome_plugins),
        "filter-mutmut": (with_stdin, filter_mutmut),
        "stryker-mutate": (with_named, stryker_mutate),
        "nextest-config": (exceptions_only, nextest_config),
    })
)


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    command, *rest = arguments
    return COMMANDS[command][0](rest, inputs)


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    command, *rest = arguments
    return COMMANDS[command][1](rest, inputs)
