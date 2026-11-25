import re
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.exceptions import Exceptions, Issue

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from checks.core.comments import Attribute, Comment, Source

PYTHON_MARKERS = FrozenList((
    r"noqa\b",
    r"ruff\s*:",
    r"type\s*:\s*ignore",
    r"(?:based)?pyright\s*:",
    r"pragma\s*:\s*no\s+(?:mutate|cover)",
    r"fmt\s*:\s*(?:off|skip)",
    r"isort\s*:\s*skip",
))
TYPESCRIPT_MARKERS = FrozenList((
    r"@ts-(?:ignore|expect-error|nocheck)",
    r"Stryker\s+(?:disable|restore)",
    r"(?:c8|istanbul|node:coverage)\s+ignore",
    r"(?:es|ox)lint-(?:disable|enable)",
    r"prettier-ignore",
))
PYTHON_MARKER = re.compile(
    rf"#\s*(?:{'|'.join(PYTHON_MARKERS)})", re.IGNORECASE
)
TYPESCRIPT_MARKER = re.compile(
    rf"(?://|/\*)\s*(?:{'|'.join(TYPESCRIPT_MARKERS)})"
)
REASON = re.compile(r'reason\s*=\s*"(?:[^"\\]|\\.)*"')
SUPPRESSING = re.compile(r"\b(allow|expect|skip)\b")
FORBIDDEN_ATTRIBUTES = FrozenOrderedSet((
    "allow",
    "mutants::skip",
    "rustfmt::skip",
))
INSTEAD = "; add an entry to exceptions.toml instead"


def is_suppression(language: str, comment: Comment) -> bool:
    if language == "python":
        return comment.kind == "line" and bool(
            PYTHON_MARKER.search(comment.text)
        )
    return language == "typescript" and bool(
        TYPESCRIPT_MARKER.search(comment.text)
    )


def markers(language: str, source: Source) -> Iterator[tuple[int, str]]:
    yield from (
        (comment.line, comment.text)
        for comment in source.comments
        if is_suppression(language, comment)
    )


def attribute_lints(arguments: str) -> FrozenList[str]:
    inner = REASON.sub("", arguments.strip()[1:-1])
    return FrozenList(part.strip() for part in inner.split(",") if part.strip())


def attribute_issue(
    file: str, attribute: Attribute, exceptions: Exceptions
) -> Iterator[Issue]:
    where, name = f"{file}:{attribute.line}", attribute.name
    arguments = attribute.arguments
    if name == "expect":
        yield from (
            Issue(where, f"#[expect({lint})] is not in exceptions.toml")
            for lint in attribute_lints(arguments)
            if not exceptions.covers(lint, file)
        )
    elif name in FORBIDDEN_ATTRIBUTES or (
        name == "cfg_attr" and SUPPRESSING.search(arguments)
    ):
        yield Issue(where, f"#[{name}{arguments}]{INSTEAD}")


def suppressions(
    language: str, sources: Mapping[str, Source], exceptions: Exceptions
) -> Iterator[Issue]:
    for file, source in sources.items():
        for attribute in source.attributes:
            yield from attribute_issue(file, attribute, exceptions)
        yield from (
            Issue(f"{file}:{line}", f"suppression `{marker}`{INSTEAD}")
            for line, marker in markers(language, source)
        )


def used_attributes(
    sources: Mapping[str, Source],
) -> FrozenOrderedSet[tuple[str, str]]:
    return FrozenOrderedSet(
        (file, lint)
        for file, source in sources.items()
        for attribute in source.attributes
        if attribute.name == "expect"
        for lint in attribute_lints(attribute.arguments)
    )
