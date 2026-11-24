from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    lookup,
    number,
    parse_json,
    posix,
    summarized,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    path: str
    line: int
    column: int
    message: str
    min_file_count: int


def parse_finding(record: Mapping[str, object]) -> Finding:
    return Finding(
        str(record.get("ruleId")),
        posix(str(record.get("file"))),
        number(lookup(record, "range.start.line")) + 1,
        number(lookup(record, "range.start.column")) + 1,
        str(record.get("message")),
        number(lookup(record, "metadata.min_file_count")),
    )


def findings(stdin: str, exceptions: Exceptions) -> FrozenList[Finding]:
    parsed = (
        parse_finding(parse_json(line))
        for line in stdin.splitlines()
        if line.strip()
    )
    return FrozenList(
        finding
        for finding in parsed
        if not exceptions.covers(f"slop:{finding.rule}", finding.path)
    )


def in_file(finding: Finding, found: Sequence[Finding]) -> int:
    return sum(
        1
        for other in found
        if (other.rule, other.path) == (finding.rule, finding.path)
    )


def reported(found: Sequence[Finding]) -> FrozenList[Finding]:
    return FrozenList(
        sorted(
            (
                finding
                for finding in found
                if in_file(finding, found) >= finding.min_file_count
            ),
            key=lambda finding: (finding.path, finding.line, finding.column),
        )
    )


def describe(finding: Finding) -> str:
    location = f"{finding.path}:{finding.line}:{finding.column}"
    return f"{location}: {finding.rule} {finding.message}"


def request(_arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS,)), stdin=True)


def run(_arguments: Sequence[str], inputs: Inputs) -> Outcome:
    found = findings(inputs.stdin, exceptions_in(inputs))
    return summarized(FrozenList(describe(f) for f in reported(found)))
