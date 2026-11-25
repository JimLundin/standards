import re
from itertools import takewhile
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.comments import UNSAFE
from checks.core.exceptions import COMMENT, Exceptions, Issue
from checks.core.suppressions import is_suppression

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from checks.core.comments import Comment, Source

RESHAPE = (
    "fix: name, type or restructure the code so it needs none,"
    " or, if it explains what we can't reshape, a `comment` exception with"
    " its reason"
)
TYPE_COMMENT = re.compile(r"#\s*type\s*:")
DIRECTIVE = re.compile(r"///\s*<reference\b")
LICENCE = re.compile(r"SPDX-License-Identifier|Copyright")
SAFETY = re.compile(r"(?://|/\*)\s*SAFETY:")


def blocks(found: FrozenList[Comment]) -> Iterator[FrozenList[Comment]]:
    start = 0
    for index in range(1, len(found) + 1):
        if (
            index == len(found)
            or found[index].line != found[index - 1].line + 1
        ):
            yield found[start:index]
            start = index


def opens_file(lines: FrozenList[str], block: FrozenList[Comment]) -> bool:
    return all(
        not line.strip() or (number == 0 and line.startswith("#!"))
        for number, line in enumerate(lines[: block[0].line - 1])
    )


def is_whole_line(lines: FrozenList[str], comment: Comment) -> bool:
    first = comment.text.splitlines()[0].strip()
    return (
        comment.kind != "docstring" and lines[comment.line - 1].strip() == first
    )


def licence(text: str, found: FrozenList[Comment]) -> FrozenList[Comment]:
    lines = FrozenList(text.splitlines())
    first = next(blocks(found), FrozenList())
    if not first or not opens_file(lines, first):
        return FrozenList()
    header = FrozenList(
        takewhile(lambda comment: is_whole_line(lines, comment), first)
    )
    named = any(LICENCE.search(comment.text) for comment in header)
    return header if named else FrozenList()


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
    yield from licence(text, found)
    for block in blocks(found):
        whole = language == "rust" and is_safety(block)
        yield from (
            comment
            for comment in block
            if whole
            or is_public_doc(comment)
            or is_suppression(language, comment)
        )


def doc_failure(language: str, comment: Comment, *, library: bool) -> str:
    if language == "python":
        return "docstring"
    if language == "typescript":
        return "JSDoc comment"
    if not library:
        return "doc comment outside a library"
    if comment.item is None:
        return "doc comment on no item, as in a macro body"
    return "doc comment on an item that isn't public in a library"


def failure(language: str, comment: Comment, *, library: bool) -> str:
    if language == "python" and TYPE_COMMENT.match(comment.text):
        return "type comment; fix: use an annotation"
    if language == "typescript" and DIRECTIVE.match(comment.text):
        return (
            "triple-slash directive; fix: name it in"
            " `compilerOptions.types` in tsconfig.json"
        )
    if comment.kind in {"doc", "docstring"}:
        return f"{doc_failure(language, comment, library=library)}; {RESHAPE}"
    return f"comment; {RESHAPE}"


def file_issues(language: str, file: str, source: Source) -> Iterator[Issue]:
    allowed = FrozenOrderedSet(kept(language, source.text, source.comments))
    yield from (
        Issue(
            f"{file}:{comment.line}",
            failure(language, comment, library=source.library),
        )
        for comment in source.comments
        if comment not in allowed
    )


def comment_issues(
    language: str, sources: Mapping[str, Source], exceptions: Exceptions
) -> Iterator[Issue]:
    for file, source in sources.items():
        if not exceptions.covers(COMMENT, file):
            yield from file_issues(language, file, source)
