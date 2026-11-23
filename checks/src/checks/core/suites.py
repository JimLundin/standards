import re
import tomllib
from dataclasses import dataclass, field
lazy from collections.abc import Iterator, Mapping, Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import entries, is_list, parse_toml, table

SUITES = "checks.toml"
TIERS = FrozenList(("commit", "step", "release"))
SUITE_KEYS = FrozenOrderedSet(("name", "command", "when"))
WHEN_KEYS = FrozenOrderedSet(("tier", "paths", "packages"))
NAME = re.compile(r"[a-z][a-z0-9-]*")
TIER_NAMES = " or ".join(f"`{tier}`" for tier in TIERS)


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


@dataclass(frozen=True, slots=True)
class Suites:
    entries: FrozenList[Suite]
    problems: FrozenList[str]


def unknown_keys(
    fields: Mapping[str, object], known: FrozenOrderedSet[str]
) -> str:
    return ", ".join(sorted(key for key in fields if key not in known))


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
        yield f"{where} has unknown keys: {unknown}"
        return
    if fields.get("tier") not in TIERS:
        yield f"{where} needs a tier: {TIER_NAMES}"
    for key in ("paths", "packages"):
        if texts(fields.get(key)) is None:
            yield f"{where} {key} must be a list of strings"
    named = texts(fields.get("packages")) or FrozenList()
    if named and language != "rust":
        yield f"{where} packages are only for Rust projects"
    elif named:
        yield from (
            f"{where} names no workspace package `{name}`"
            for name in named
            if name not in packages
        )


def parse_trigger(fields: Mapping[str, object]) -> Trigger:
    return Trigger(
        str(fields.get("tier")),
        texts(fields.get("paths")) or FrozenList(),
        texts(fields.get("packages")) or FrozenList(),
    )


def suite_problems(
    where: str,
    fields: Mapping[str, object],
    language: str,
    packages: Sequence[str],
) -> Iterator[str]:
    unknown = unknown_keys(fields, SUITE_KEYS)
    if unknown:
        yield f"{where} has unknown keys: {unknown}"
        return
    name, command = fields.get("name"), fields.get("command")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        yield f"{where} needs a name of lowercase letters, digits and -"
    if not isinstance(command, str) or not command.strip():
        yield f"{where} needs a command"
    elif "\n" in command or "\t" in command:
        yield f"{where} command must be one line without tabs"
    whens = entries(fields.get("when"))
    if not whens:
        yield f"{where} needs at least one [[suite.when]]"
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
    )


def load(text: str | None, language: str, packages: Sequence[str]) -> Suites:
    try:
        data = parse_toml(text)
    except tomllib.TOMLDecodeError as error:
        return Suites(FrozenList(), FrozenList((f"{SUITES}: {error}",)))
    problems = FrozenList(
        f"{SUITES}: unknown table `{key}`" for key in data if key != "suite"
    )
    names: FrozenList[str] = FrozenList()
    suites: FrozenList[Suite] = FrozenList()
    for index, entry in enumerate(entries(data.get("suite"))):
        fields = table(entry)
        where = f"{SUITES}: suite {index + 1}"
        found = FrozenList(suite_problems(where, fields, language, packages))
        if fields.get("name") in names:
            found += (f"{where} repeats the name `{fields.get('name')}`",)
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
