from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
from checks.core.python_source import Finding, describe
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    json_object,
    posix,
    required_integer,
    required_string,
    required_table,
    summarized,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

NO_THRESHOLD = 0
RULES = "python/slop/rules"


@dataclass(frozen=True, slots=True)
class Match:
    path: str
    finding: Finding
    min_file_count: int


def min_file_count(record: Mapping[str, object]) -> int:
    if "min_file_count" not in required_table(record, "metadata"):
        return NO_THRESHOLD
    return required_integer(record, "metadata.min_file_count")


def parse_match(record: Mapping[str, object]) -> Match:
    finding = Finding(
        required_integer(record, "range.start.line") + 1,
        required_integer(record, "range.start.column"),
        required_string(record, "ruleId"),
        required_string(record, "message"),
    )
    path = posix(required_string(record, "file"))
    return Match(path, finding, min_file_count(record))


def matches(stdin: str, exceptions: Exceptions) -> FrozenList[Match]:
    parsed = (
        parse_match(json_object(line))
        for line in stdin.splitlines()
        if line.strip()
    )
    return FrozenList(
        match
        for match in parsed
        if not exceptions.covers(f"slop:{match.finding.rule}", match.path)
    )


def reported(found: Sequence[Match]) -> FrozenList[Match]:
    in_file = FrozenOrderedDict[tuple[str, str], int](
        Counter((match.finding.rule, match.path) for match in found)
    )
    return FrozenList(
        sorted(
            (
                match
                for match in found
                if in_file[match.finding.rule, match.path]
                >= match.min_file_count
            ),
            key=lambda match: (
                match.path,
                match.finding.line,
                match.finding.column,
            ),
        )
    )


def rule_file(standards: str, rule: str) -> str:
    return f"{standards}/{RULES}/{rule.removeprefix('slop:')}.yml"


def request(_arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)), stdin=True)


def run(_arguments: Sequence[str], inputs: Inputs) -> Outcome:
    found = matches(inputs.stdin, exceptions_in(inputs))
    return summarized(
        FrozenList(describe(m.path, m.finding) for m in reported(found))
    )
