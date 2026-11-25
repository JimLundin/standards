import re
import tomllib
from dataclasses import dataclass, field
lazy from collections.abc import Iterator, Mapping, Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import entries, is_list, parse_toml, table

SUITES = "checks.toml"
TIERS = FrozenList(("commit", "step", "release"))
SUITE_KEYS = FrozenOrderedSet(("name", "command", "tools", "when"))
WHEN_KEYS = FrozenOrderedSet(("tier", "paths", "packages"))
NAME = re.compile(r"[a-z][a-z0-9-]*")
TIER_NAMES = " or ".join(f"`{tier}`" for tier in TIERS)
SUITE = "[[suite]]"
SUITE_KEY_NAMES = ", ".join(f"`{key}`" for key in SUITE_KEYS)
WHEN_KEY_NAMES = ", ".join(f"`{key}`" for key in WHEN_KEYS)
STRINGS = (
    "must be a list of strings; fix: write it as a list of non-empty strings"
)


@dataclass(frozen=True, slots=True)
class Trigger:
    tier: str
    paths: FrozenList[str] = field(default_factory=FrozenList)
    packages: FrozenList[str] = field(default_factory=FrozenList)


@dataclass(frozen=True, slots=True)
class Suite:
    name: str
    command: str
    triggers: FrozenList[Trigger]
    tools: FrozenList[str] = field(default_factory=FrozenList)


@dataclass(frozen=True, slots=True)
class Suites:
    entries: FrozenList[Suite]
    problems: FrozenList[str]


def unknown_keys(
    fields: Mapping[str, object], known: FrozenOrderedSet[str]
) -> str:
    return ", ".join(sorted(key for key in fields if key not in known))


def unknown_problem(where: str, unknown: str, known: str) -> str:
    return f"{where} has unknown keys: {unknown}; fix: remove them, keeping {known}"


def texts(value: object) -> FrozenList[str] | None:
    if value is None:
        return FrozenList()
    items = entries(value)
    if not is_list(value) or not all(
        isinstance(item, str) and item for item in items
    ):
        return None
    return FrozenList(str(item) for item in items)


def trigger_problems(
    where: str,
    fields: Mapping[str, object],
    language: str,
    packages: Sequence[str],
) -> Iterator[str]:
    unknown = unknown_keys(fields, WHEN_KEYS)
    if unknown:
        yield unknown_problem(where, unknown, WHEN_KEY_NAMES)
        return
    if fields.get("tier") not in TIERS:
        yield f"{where} has no valid tier; fix: set `tier` to {TIER_NAMES}"
    for key in ("paths", "packages"):
        if texts(fields.get(key)) is None:
            yield f'{where} {key} {STRINGS}, such as `{key} = ["x"]`'
    named = texts(fields.get("packages")) or FrozenList()
    if named and language != "rust":
        yield (
            f"{where} packages are only for Rust projects; fix: name the files"
            " in `paths` instead"
        )
    elif named:
        yield from (
            (
                f"{where} names no workspace package `{name}`; fix: name a"
                f" package of the workspace, or remove `{name}`"
            )
            for name in named
            if name not in packages
        )


def parse_trigger(fields: Mapping[str, object]) -> Trigger:
    return Trigger(
        str(fields.get("tier")),
        texts(fields.get("paths")) or FrozenList(),
        texts(fields.get("packages")) or FrozenList(),
    )


def tool_problems(
    where: str, value: object, pinned: Sequence[str]
) -> Iterator[str]:
    tools = texts(value)
    if tools is None:
        yield f'{where} tools {STRINGS}, such as `tools = ["NODE"]`'
        return
    yield from (
        (
            f"{where} names no pinned tool `{tool}`; fix: pin `{tool}` in"
            f" tools.env, or remove it from `tools`"
        )
        for tool in tools
        if tool not in pinned
    )


def suite_problems(
    where: str,
    fields: Mapping[str, object],
    language: str,
    packages: Sequence[str],
    pinned: Sequence[str],
) -> Iterator[str]:
    unknown = unknown_keys(fields, SUITE_KEYS)
    if unknown:
        yield unknown_problem(where, unknown, SUITE_KEY_NAMES)
        return
    name, command = fields.get("name"), fields.get("command")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        yield (
            f"{where} has no name of lowercase letters, digits and -; fix: set"
            ' `name`, such as `name = "ip-scrub"`'
        )
    if not isinstance(command, str) or not command.strip():
        yield (
            f"{where} has no command; fix: set `command` to the line that"
            " runs the suite"
        )
    elif "\n" in command or "\t" in command:
        yield (
            f"{where} command spans lines or holds tabs; fix: write it on one"
            " line without tabs, or move it into a script"
        )
    yield from tool_problems(where, fields.get("tools"), pinned)
    whens = entries(fields.get("when"))
    if not whens:
        yield (
            f"{where} has no [[suite.when]]; fix: add a [[suite.when]] with"
            f" a `tier` of {TIER_NAMES}"
        )
    for index, when in enumerate(whens, start=1):
        yield from trigger_problems(
            f"{where} when {index}", table(when), language, packages
        )


def parse_suite(fields: Mapping[str, object]) -> Suite:
    return Suite(
        str(fields.get("name")),
        str(fields.get("command")).strip(),
        FrozenList(
            parse_trigger(table(when)) for when in entries(fields.get("when"))
        ),
        texts(fields.get("tools")) or FrozenList(),
    )


def load(
    text: str | None,
    language: str,
    packages: Sequence[str],
    pinned: Sequence[str] = (),
) -> Suites:
    try:
        data = parse_toml(text)
    except tomllib.TOMLDecodeError as error:
        problem = f"{SUITES}: {error}; fix: correct the TOML there"
        return Suites(FrozenList(), FrozenList((problem,)))
    problems = FrozenList(
        f"{SUITES}: unknown table `{key}`; fix: remove it, or make it a {SUITE}"
        for key in data
        if key != "suite"
    )
    names: FrozenList[str] = FrozenList()
    suites: FrozenList[Suite] = FrozenList()
    for index, entry in enumerate(entries(data.get("suite"))):
        fields = table(entry)
        where = f"{SUITES}: suite {index + 1}"
        found = FrozenList(
            suite_problems(where, fields, language, packages, pinned)
        )
        if fields.get("name") in names:
            found += (
                (
                    f"{where} repeats the name `{fields.get('name')}`; fix:"
                    " give each suite its own name"
                ),
            )
        names += (str(fields.get("name")),)
        problems += found
        if not found:
            suites += (parse_suite(fields),)
    return Suites(suites, problems)


def at(tier: str, trigger: Trigger) -> bool:
    return TIERS.index(trigger.tier) <= TIERS.index(tier)


def active(suite: Suite, tier: str) -> FrozenList[Trigger]:
    return FrozenList(
        trigger for trigger in suite.triggers if at(tier, trigger)
    )
