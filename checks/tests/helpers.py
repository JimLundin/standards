from pathlib import Path
lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedDict

from checks.core.values import Inputs, Outcome

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
