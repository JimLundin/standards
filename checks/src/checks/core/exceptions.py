import re
import tomllib
from dataclasses import dataclass
from itertools import starmap
lazy from collections.abc import Container, Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import (
    Inputs,
    entries,
    matches,
    parse_toml,
    table,
    within,
)

EXCEPTIONS = "exceptions.toml"
FIELDS = FrozenOrderedSet(("path", "rule", "reason"))
API = "api"
SHELL = "shell"
FLAKY = "flaky"
BOX = "box"
MUTATION = "mutation"
RUST_RULES = FrozenOrderedSet((API, SHELL, FLAKY, BOX))
UNPATHED = FrozenOrderedSet(("drift", FLAKY))
IMMUTABILITY = re.compile(r"IMM\d{3}")
PURITY = re.compile(r"PUR\d{3}(?::[\w.]+)?")
RUST_LINT = re.compile(r"(?:clippy::)?[a-z_]+")
OXLINT = re.compile(r"lint/([\w-]+)/([\w-]+)")


def rule_covers(excepted: str, found: str) -> bool:
    if not PURITY.fullmatch(excepted):
        return excepted == found
    code, _, prefix = excepted.partition(":")
    found_code, _, module = found.partition(":")
    return code == found_code and (not prefix or within(module, (prefix,)))


@dataclass(frozen=True, slots=True)
class ExceptionEntry:
    path: str
    rule: str
    reason: str

    def covers(self, rule: str, path: str) -> bool:
        return rule_covers(self.rule, rule) and matches(path, self.path)


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    message: str
    rule: str = ""


@dataclass(frozen=True, slots=True)
class Exceptions:
    entries: FrozenList[ExceptionEntry]
    problems: FrozenList[Issue]

    def covers(self, rule: str, path: str) -> bool:
        return any(entry.covers(rule, path) for entry in self.entries)

    def paths(self, rule: str) -> FrozenList[str]:
        return FrozenList(
            entry.path
            for entry in self.entries
            if rule_covers(entry.rule, rule)
        )


def parse_entry(index: int, entry: object) -> ExceptionEntry | Issue:
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
        return ExceptionEntry(path, rule, reason)
    return Issue(EXCEPTIONS, f"{where} needs a path, a rule and a reason")


def load(text: str | None) -> Exceptions:
    try:
        data = parse_toml(text)
    except tomllib.TOMLDecodeError as error:
        problem = Issue(EXCEPTIONS, f"invalid TOML: {error}")
        return Exceptions(FrozenList(), FrozenList((problem,)))
    parsed = FrozenList(
        starmap(parse_entry, enumerate(entries(data.get("exception"))))
    )
    unknown = FrozenList(
        Issue(EXCEPTIONS, f"unknown table `{key}`")
        for key in data
        if key != "exception"
    )
    return Exceptions(
        FrozenList(item for item in parsed if isinstance(item, ExceptionEntry)),
        FrozenList(item for item in parsed if isinstance(item, Issue))
        + unknown,
    )


def exceptions_in(inputs: Inputs) -> Exceptions:
    return load(inputs.texts.get(EXCEPTIONS))


def kind(language: str, rule: str) -> str:
    if rule == MUTATION or (language == "rust" and rule in RUST_RULES):
        return rule
    if rule.startswith("drift:"):
        return "drift"
    if language == "python":
        return python_kind(rule)
    if language == "rust" and RUST_LINT.fullmatch(rule):
        return "attribute"
    if language == "typescript" and OXLINT.fullmatch(rule):
        return "oxlint"
    return ""


def python_kind(rule: str) -> str:
    if IMMUTABILITY.fullmatch(rule):
        return "immutability"
    if PURITY.fullmatch(rule):
        return "purity"
    return "unused" if rule == "unused" else "ruff"


def invalidity(
    language: str,
    entry: ExceptionEntry,
    files: Sequence[str],
    attributes: Container[tuple[str, str]],
) -> str:
    rule_kind = kind(language, entry.rule)
    matched = FrozenList(file for file in files if matches(file, entry.path))
    if not rule_kind:
        return f"unknown rule for {language}"
    if rule_kind not in UNPATHED and not matched:
        return "path matches no tracked file"
    if rule_kind == "attribute" and not any(
        (file, entry.rule) in attributes for file in matched
    ):
        return "no matching #[expect] attribute; remove the entry"
    return ""


def validate(
    language: str,
    exceptions: Exceptions,
    files: Sequence[str],
    attributes: Container[tuple[str, str]],
) -> FrozenList[Issue]:
    return exceptions.problems + FrozenList(
        Issue(f"{EXCEPTIONS} ({entry.path}, {entry.rule})", message)
        for entry in exceptions.entries
        if (message := invalidity(language, entry, files, attributes))
    )
