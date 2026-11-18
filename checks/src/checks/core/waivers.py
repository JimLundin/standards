import re
import tomllib
from dataclasses import dataclass
from itertools import starmap
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import entries, matches, parse_toml, table

EXCEPTIONS = "exceptions.toml"
FIELDS = FrozenOrderedSet(("path", "rule", "reason"))
RUST_RULES = FrozenOrderedSet(("api", "shell", "flaky"))
IMMUTABILITY = re.compile(r"IMM\d{3}")
PURITY = re.compile(r"PUR\d{3}(?::[\w.]+)?")
RUST_LINT = re.compile(r"(?:clippy::)?[a-z_]+")


@dataclass(frozen=True, slots=True)
class Waiver:
    path: str
    rule: str
    reason: str

    def covers(self, path: str, rule: str) -> bool:
        return self.rule == rule and matches(path, self.path)


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    message: str
    rule: str = ""


@dataclass(frozen=True, slots=True)
class Waivers:
    entries: FrozenList[Waiver]
    problems: FrozenList[Issue]


def parse_waiver(index: int, entry: object) -> Waiver | Issue:
    fields = table(entry)
    where = f"exception {index + 1}"
    unknown = sorted(key for key in fields if key not in FIELDS)
    if unknown:
        keys = ", ".join(unknown)
        return Issue(EXCEPTIONS, f"{where} has unknown keys: {keys}")
    values = FrozenList(fields.get(key) for key in FIELDS)
    texts = FrozenList(
        value.strip() for value in values if isinstance(value, str)
    )
    if len(texts) == len(values) and all(texts):
        path, rule, reason = texts
        return Waiver(path, rule, reason)
    return Issue(EXCEPTIONS, f"{where} needs a path, a rule and a reason")


def load(text: str | None) -> Waivers:
    try:
        data = parse_toml(text)
    except tomllib.TOMLDecodeError as error:
        problem = Issue(EXCEPTIONS, f"invalid TOML: {error}")
        return Waivers(FrozenList(), FrozenList((problem,)))
    parsed = FrozenList(
        starmap(parse_waiver, enumerate(entries(data.get("exception"))))
    )
    unknown = FrozenList(
        Issue(EXCEPTIONS, f"unknown table `{key}`")
        for key in data
        if key != "exception"
    )
    return Waivers(
        FrozenList(item for item in parsed if isinstance(item, Waiver)),
        FrozenList(item for item in parsed if isinstance(item, Issue))
        + unknown,
    )


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
    if PURITY.fullmatch(rule):
        return "purity"
    return "unused" if rule == "unused" else "ruff"


def waived(waivers: Sequence[Waiver], path: str, rule: str) -> bool:
    return any(waiver.covers(path, rule) for waiver in waivers)
