from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
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


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    path: str
    line: int
    column: int
    message: str
    min_file_count: int


def min_file_count(record: Mapping[str, object]) -> int:
    if "min_file_count" not in required_table(record, "metadata"):
        return NO_THRESHOLD
    return required_integer(record, "metadata.min_file_count")


def parse_finding(record: Mapping[str, object]) -> Finding:
    return Finding(
        required_string(record, "ruleId"),
        posix(required_string(record, "file")),
        required_integer(record, "range.start.line") + 1,
        required_integer(record, "range.start.column") + 1,
        required_string(record, "message"),
        min_file_count(record),
    )


def findings(stdin: str, exceptions: Exceptions) -> FrozenList[Finding]:
    parsed = (
        parse_finding(json_object(line))
        for line in stdin.splitlines()
        if line.strip()
    )
    return FrozenList(
        finding
        for finding in parsed
        if not exceptions.covers(f"slop:{finding.rule}", finding.path)
    )


def reported(found: Sequence[Finding]) -> FrozenList[Finding]:
    in_file = FrozenOrderedDict[tuple[str, str], int](
        Counter((finding.rule, finding.path) for finding in found)
    )
    return FrozenList(
        sorted(
            (
                finding
                for finding in found
                if in_file[finding.rule, finding.path] >= finding.min_file_count
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
