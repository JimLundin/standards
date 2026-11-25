import re
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.comments import Comment, comments, is_source
from checks.core.exceptions import COMMENT, Exceptions, Issue
from checks.core.suppressions import is_suppression

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

FIX = (
    "comment; fix: name, type or restructure the code so it needs none,"
    " or, if it explains what we can't reshape, a `comment` exception with"
    " its reason"
)
LICENCE = re.compile(r"SPDX-License-Identifier|Copyright")
SAFETY = re.compile(r"(?://|/\*)\s*SAFETY:")
UNSAFE = "unsafe_block"


def blocks(found: FrozenList[Comment]) -> Iterator[FrozenList[Comment]]:
    start = 0
    for index in range(1, len(found) + 1):
        if (
            index == len(found)
            or found[index].line != found[index - 1].line + 1
        ):
            yield found[start:index]
            start = index


def opens_file(text: str, block: FrozenList[Comment]) -> bool:
    before = text.splitlines()[: block[0].line - 1]
    return all(
        not line.strip() or (number == 0 and line.startswith("#!"))
        for number, line in enumerate(before)
    )


def is_licence(text: str, block: FrozenList[Comment]) -> bool:
    return opens_file(text, block) and any(
        LICENCE.search(comment.text) for comment in block
    )


def is_safety(block: FrozenList[Comment]) -> bool:
    return bool(SAFETY.match(block[0].text)) and block[-1].precedes == UNSAFE


def is_public_doc(comment: Comment) -> bool:
    return (
        comment.kind == "doc"
        and comment.item is not None
        and comment.item.public
    )


def kept(
    language: str, text: str, found: FrozenList[Comment]
) -> Iterator[Comment]:
    for index, block in enumerate(blocks(found)):
        whole = (index == 0 and is_licence(text, block)) or (
            language == "rust" and is_safety(block)
        )
        yield from (
            comment
            for comment in block
            if whole
            or is_public_doc(comment)
            or is_suppression(language, comment)
        )


def file_issues(
    language: str, file: str, text: str, *, library: bool
) -> Iterator[Issue]:
    found = FrozenList(comments(file, text, library=library))
    allowed = FrozenOrderedSet(kept(language, text, found))
    yield from (
        Issue(f"{file}:{comment.line}", FIX)
        for comment in found
        if comment not in allowed
    )


def comment_issues(
    language: str,
    texts: Mapping[str, str],
    exceptions: Exceptions,
    libraries: FrozenOrderedSet[str],
) -> Iterator[Issue]:
    for file, text in texts.items():
        if is_source(language, file) and not exceptions.covers(COMMENT, file):
            yield from file_issues(
                language, file, text, library=file in libraries
            )
