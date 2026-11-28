from dataclasses import dataclass
from typing import Literal
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedDict

from checks.core.values import Inputs, Outcome, Request, listing, matches

type Side = Literal["sources", "tests"]
type Language = Literal["python", "typescript"]

SIDES: FrozenOrderedDict[str, Side] = FrozenOrderedDict({
    "sources": "sources",
    "tests": "tests",
})
OTHER: FrozenOrderedDict[Side, Side] = FrozenOrderedDict({
    "sources": "tests",
    "tests": "sources",
})
TYPESCRIPT_EXTENSIONS = FrozenList((
    "js",
    "mjs",
    "cjs",
    "jsx",
    "ts",
    "tsx",
    "mts",
    "cts",
))
TEST_FOLDERS = FrozenList(("**/test/**", "**/tests/**", "**/__tests__/**"))


@dataclass(frozen=True, slots=True)
class Files:
    files: FrozenList[str]
    tests: FrozenList[str]


LANGUAGES: FrozenOrderedDict[Language, Files] = FrozenOrderedDict({
    "python": Files(
        FrozenList(("**/*.py", "**/*.pyw")),
        FrozenList(("**/test_*.py", "**/conftest.py")),
    ),
    "typescript": Files(
        FrozenList(f"**/*.{extension}" for extension in TYPESCRIPT_EXTENSIONS),
        FrozenList(("**/*.test.*", "**/*.spec.*")),
    ),
})


def tests_of(language: Language) -> FrozenList[str]:
    return TEST_FOLDERS + LANGUAGES[language].tests


def side_of(path: str) -> Side | None:
    language = next(
        (
            files
            for files in LANGUAGES.values()
            if any(matches(path, glob) for glob in files.files)
        ),
        None,
    )
    if language is None:
        return None
    if any(matches(path, glob) for glob in TEST_FOLDERS + language.tests):
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
