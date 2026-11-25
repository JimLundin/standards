import re
from pathlib import Path
lazy from collections.abc import Iterable, Mapping

from ordered import FrozenList, FrozenOrderedDict

from checks.core.values import Inputs, Outcome
lazy from checks.core.exceptions import Issue

# The standards checkout: the nearest folder above holding lib.sh, so that
# mutmut's copy of the tests, under checks/mutants/, finds it too.
STANDARDS = next(
    folder
    for folder in Path(__file__).resolve().parents
    if (folder / "lib.sh").is_file()
)


def entry(path: str, rule: str, reason: str = "r") -> str:
    return f'[[exception]]\npath = "{path}"\nrule = "{rule}"\nreason = "{reason}"\n'


def inputs(texts: Mapping[str, str], stdin: str = "", cwd: str = "") -> Inputs:
    return Inputs(FrozenOrderedDict(texts), stdin, cwd)


def lines(outcome: Outcome) -> FrozenList[str]:
    return outcome.lines


FIX = "; fix: "
ESCAPE = re.compile(r"exception")
ALTERNATIVE = re.compile(r"\bor\b")


def assert_names_the_fix(message: str) -> None:
    wrong, separator, change = message.partition(FIX)
    assert wrong.strip(), message
    assert separator, message
    assert change.strip(), message
    assert "exceptions.toml" not in wrong, message
    escape = ESCAPE.search(change)
    if escape is not None:
        assert ALTERNATIVE.search(change[: escape.start()]), message


def assert_each_names_the_fix(issues: Iterable[Issue]) -> None:
    for issue in issues:
        assert_names_the_fix(issue.message)
