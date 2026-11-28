from typing import Literal
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedDict

from checks.core.values import Inputs, Outcome, Request, listing, matches

type Side = Literal["sources", "tests"]

PYTHON_FILES = FrozenList(("**/*.py", "**/*.pyw"))
TEST_FILES = FrozenList(("**/tests/**", "**/test_*.py", "**/conftest.py"))
OTHER: FrozenOrderedDict[str, Side] = FrozenOrderedDict({
    "sources": "tests",
    "tests": "sources",
})


def side_of(path: str) -> Side | None:
    if not any(matches(path, glob) for glob in PYTHON_FILES):
        return None
    if any(matches(path, glob) for glob in TEST_FILES):
        return "tests"
    return "sources"


def request(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(stdin=True)


def run(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            f"{side}\t{path}"
            for path in inputs.stdin.splitlines()
            if (side := side_of(path))
        )
    )
