import re
import tomllib
from dataclasses import dataclass, field
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.cache import TIERS
from checks.core.values import entries, is_list, matches, parse_toml, table

SUITES = "checks.toml"
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


@dataclass(frozen=True, slots=True)
class Changes:
    files: FrozenList[str]
    packages: FrozenList[str]
    everything: bool = False


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
) -> FrozenList[str]:
    unknown = unknown_keys(fields, WHEN_KEYS)
    if unknown:
        return FrozenList((f"{where} has unknown keys: {unknown}",))
    problems: FrozenList[str] = FrozenList()
    if fields.get("tier") not in TIERS:
        problems += (f"{where} needs a tier: {TIER_NAMES}",)
    for key in ("paths", "packages"):
        if texts(fields.get(key)) is None:
            problems += (f"{where} {key} must be a list of strings",)
    named = texts(fields.get("packages")) or FrozenList()
    if named and language != "rust":
        problems += (f"{where} packages are only for Rust projects",)
    elif named:
        problems += tuple(
            f"{where} names no workspace package `{name}`"
            for name in named
            if name not in packages
        )
    return problems


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
) -> FrozenList[str]:
    unknown = unknown_keys(fields, SUITE_KEYS)
    if unknown:
        return FrozenList((f"{where} has unknown keys: {unknown}",))
    name, command = fields.get("name"), fields.get("command")
    problems: FrozenList[str] = FrozenList()
    if not isinstance(name, str) or not NAME.fullmatch(name):
        problems += (
            f"{where} needs a name of lowercase letters, digits and -",
        )
    if not isinstance(command, str) or not command.strip():
        problems += (f"{where} needs a command",)
    elif "\n" in command or "\t" in command:
        problems += (f"{where} command must be one line without tabs",)
    whens = entries(fields.get("when"))
    if not whens:
        problems += (f"{where} needs at least one [[suite.when]]",)
    for index, when in enumerate(whens):
        problems += trigger_problems(
            f"{where} when {index + 1}", table(when), language, packages
        )
    return problems


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
        found = suite_problems(where, fields, language, packages)
        if fields.get("name") in names:
            found += (f"{where} repeats the name `{fields.get('name')}`",)
        names += (str(fields.get("name")),)
        problems += found
        if not found:
            suites += (parse_suite(fields),)
    return Suites(suites, problems)


def fires(trigger: Trigger, changes: Changes) -> bool:
    if changes.everything:
        return True
    if not trigger.paths and not trigger.packages:
        return bool(changes.files)
    return any(
        matches(file, glob) for file in changes.files for glob in trigger.paths
    ) or any(package in changes.packages for package in trigger.packages)


def at(tier: str, trigger: Trigger) -> bool:
    return TIERS.index(trigger.tier) <= TIERS.index(tier)


def triggered(
    suites: Sequence[Suite], tier: str, changes: Changes
) -> FrozenList[Suite]:
    return FrozenList(
        suite
        for suite in suites
        if any(
            at(tier, trigger) and fires(trigger, changes)
            for trigger in suite.triggers
        )
    )
