import json

from ordered import FrozenList, FrozenOrderedDict

from checks.core.slop import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import entry

SENTINEL = "sentinel-fallback-function"
MESSAGE = "swallows every error and returns a sentinel"


def finding(
    path: str,
    line: int,
    rule: str = SENTINEL,
    metadata: dict[str, object] | None = None,
) -> str:
    return json.dumps({
        "file": path,
        "range": {"start": {"line": line, "column": 4}},
        "ruleId": rule,
        "message": MESSAGE,
        "metadata": {"min_file_count": 2} if metadata is None else metadata,
    })


def scanned(*findings: str, exceptions: str | None = None) -> Outcome:
    texts = FrozenOrderedDict(
        {} if exceptions is None else {"exceptions.toml": exceptions}
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


def test_a_rule_without_a_file_count_reports_its_first_finding() -> None:
    outcome = scanned(finding("src/a.py", 0, "for-range-len", {}))
    assert outcome.lines == (
        f"src/a.py:1:5: for-range-len {MESSAGE}",
        "Found 1 issues",
    )


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
