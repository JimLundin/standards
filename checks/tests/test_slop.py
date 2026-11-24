import json
import re
lazy from collections.abc import Mapping

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.slop import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import entry

SENTINEL = "sentinel-fallback-function"
GUARD = "isinstance-guard-raise"
MESSAGE = "swallows every error and returns a sentinel"


def fields(
    path: str,
    line: int,
    rule: str = SENTINEL,
    metadata: Mapping[str, object] | None = None,
    severity: str = "warning",
) -> dict[str, object]:
    return {
        "file": path,
        "range": {"start": {"line": line, "column": 4}},
        "ruleId": rule,
        "severity": severity,
        "message": MESSAGE,
        "metadata": metadata if metadata is not None else {"min_file_count": 2},
    }


def finding(
    path: str,
    line: int,
    rule: str = SENTINEL,
    metadata: Mapping[str, object] | None = None,
    severity: str = "warning",
) -> str:
    return json.dumps(fields(path, line, rule, metadata, severity))


def scanned(*findings: str, exceptions: str | None = None) -> Outcome:
    texts = FrozenOrderedDict(
        {"exceptions.toml": exceptions} if exceptions is not None else {}
    )
    return run((), Inputs(texts, "".join(f"{f}\n" for f in findings)))


def test_request_reads_the_exceptions_and_the_findings_on_stdin() -> None:
    assert request((), Inputs()) == Request(
        FrozenList(("exceptions.toml",)), stdin=True
    )


def test_a_rule_below_its_file_count_passes() -> None:
    outcome = scanned(finding("src/a.py", 2))
    assert outcome.lines == ("All checks passed",)
    assert outcome.status == 0


def test_a_rule_at_its_file_count_reports_each_finding() -> None:
    outcome = scanned(finding("src/a.py", 2), finding("src/a.py", 9))
    assert outcome.lines == (
        f"src/a.py:3:5: {SENTINEL} {MESSAGE}",
        f"src/a.py:10:5: {SENTINEL} {MESSAGE}",
        "Found 2 issues",
    )
    assert outcome.status == 1


def test_the_file_count_is_per_file_and_per_rule() -> None:
    outcome = scanned(
        finding("src/a.py", 2),
        finding("src/b.py", 2),
        finding("src/b.py", 5, "except-return-static-sentinel"),
    )
    assert outcome.lines == ("All checks passed",)


def test_a_rule_gates_whatever_its_severity() -> None:
    outcome = scanned(
        finding("src/a.py", 2, GUARD, severity="info"),
        finding("src/a.py", 9, GUARD, severity="info"),
    )
    assert outcome.lines == (
        f"src/a.py:3:5: {GUARD} {MESSAGE}",
        f"src/a.py:10:5: {GUARD} {MESSAGE}",
        "Found 2 issues",
    )
    assert outcome.status == 1


def test_a_rule_without_a_file_count_reports_its_first_finding() -> None:
    outcome = scanned(finding("src/a.py", 0, "for-range-len", {}))
    assert outcome.lines == (
        f"src/a.py:1:5: for-range-len {MESSAGE}",
        "Found 1 issues",
    )


def test_a_rule_with_metadata_but_no_file_count_reports_its_first_finding() -> (
    None
):
    outcome = scanned(
        finding("src/a.py", 0, "for-range-len", {"category": "slop"})
    )
    assert outcome.lines == (
        f"src/a.py:1:5: for-range-len {MESSAGE}",
        "Found 1 issues",
    )


def without(key: str) -> str:
    record = fields("src/a.py", 2)
    return json.dumps({name: record[name] for name in record if name != key})


@pytest.mark.parametrize(
    ("line", "error"),
    [
        (without("ruleId"), "`ruleId` is not a string: None"),
        (without("file"), "`file` is not a string: None"),
        (without("message"), "`message` is not a string: None"),
        (without("range"), "`range.start.line` is not an integer: None"),
        (
            json.dumps({**fields("src/a.py", 2), "range": {}}),
            "`range.start.line` is not an integer: None",
        ),
        (without("metadata"), "`metadata` is not a table: None"),
        (
            finding("src/a.py", 2, metadata={"min_file_count": "2"}),
            "`metadata.min_file_count` is not an integer: '2'",
        ),
        ("[1]", "not a JSON object: '[1]'"),
    ],
)
def test_a_malformed_record_fails_naming_what_is_wrong(
    line: str, error: str
) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(error)}"):
        _ = scanned(line)


def test_an_exception_drops_the_findings_of_its_rule_in_its_paths() -> None:
    outcome = scanned(
        finding("src/a.py", 2),
        finding("src/a.py", 9),
        exceptions=entry("src/*.py", f"slop:{SENTINEL}"),
    )
    assert outcome.lines == ("All checks passed",)


def test_an_exception_of_another_rule_drops_nothing() -> None:
    outcome = scanned(
        finding("src/a.py", 2),
        finding("src/a.py", 9),
        exceptions=entry("src/*.py", "slop:for-range-len"),
    )
    assert outcome.lines[-1] == "Found 2 issues"
