import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import plugin_paths
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
from checks.core.waivers import EXCEPTIONS, Waiver, kind, load, waived

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def waivers_of(inputs: Inputs) -> FrozenList[Waiver]:
    return load(inputs.texts.get(EXCEPTIONS)).entries


def ruff_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    rules: FrozenOrderedDict[str, FrozenList[str]] = FrozenOrderedDict()
    for waiver in waivers_of(inputs):
        if kind("python", waiver.rule) == "ruff":
            known = rules.get(waiver.path, FrozenList())
            rules |= {waiver.path: FrozenList((*known, waiver.rule))}
    if not rules:
        return Outcome()
    pairs = ", ".join(
        f"{json.dumps(path)} = {json.dumps(list(names))}"
        for path, names in rules.items()
    )
    return listing((f"lint.extend-per-file-ignores = {{{pairs}}}",))


def immutability_args(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            f"--skip={waiver.rule}:{waiver.path}"
            for waiver in waivers_of(inputs)
            if kind("python", waiver.rule) == "immutability"
        )
    )


def purity_args(_: Sequence[str], inputs: Inputs) -> Outcome:
    pairs = [
        [waiver.rule, waiver.path]
        for waiver in waivers_of(inputs)
        if kind("python", waiver.rule) == "purity"
    ]
    return listing((f"--skips={json.dumps(pairs)}",) if pairs else ())


def without(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    rule, *files = arguments
    waivers = waivers_of(inputs)
    return listing(
        FrozenList(file for file in files if not waived(waivers, file, rule))
    )


def globs_of(rule: str, waivers: Sequence[Waiver]) -> FrozenList[str]:
    return FrozenList(waiver.path for waiver in waivers if waiver.rule == rule)


def globs(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(globs_of(arguments[0], waivers_of(inputs)))


def biome_skips(file: str, waivers: Sequence[Waiver]) -> FrozenList[str]:
    return FrozenList(
        sorted(
            waiver.rule.removeprefix("lint/")
            for waiver in waivers
            if waiver.rule.startswith("lint/")
            and not waiver.rule.startswith("lint/plugin/")
            and waiver.covers(file, waiver.rule)
        )
    )


def biome_groups(files: Sequence[str], inputs: Inputs) -> Outcome:
    waivers = waivers_of(inputs)
    groups: FrozenOrderedDict[FrozenList[str], FrozenList[str]] = (
        FrozenOrderedDict()
    )
    for file in files:
        skips = biome_skips(file, waivers)
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
    waivers = waivers_of(inputs)
    return listing(
        FrozenList(
            line
            for line in inputs.stdin.splitlines()
            if not any(
                waived(waivers, file, "mutation")
                for file in module_files(line.strip().rsplit(".", 1)[0])
            )
        )
    )


def stryker_mutate(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    config = parse_json(inputs.texts.get(arguments[0]))
    return listing((
        ",".join((
            *strings(config.get("mutate")),
            *(f"!{glob}" for glob in globs_of("mutation", waivers_of(inputs))),
        )),
    ))


def nextest_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            line
            for glob in globs_of("flaky", waivers_of(inputs))
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
        "immutability-args": (exceptions_only, immutability_args),
        "purity-args": (exceptions_only, purity_args),
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
