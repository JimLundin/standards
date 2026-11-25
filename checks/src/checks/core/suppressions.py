import re
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import Exceptions, Issue

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from checks.core.comments import Attribute, Comment, Source

PYTHON_MARKERS = FrozenOrderedDict({
    r"noqa\b": "ruff",
    r"ruff\s*:": "ruff",
    r"type\s*:\s*ignore": "basedpyright",
    r"(?:based)?pyright\s*:": "basedpyright",
    r"pragma\s*:\s*no\s+mutate": "mutmut",
    r"pragma\s*:\s*no\s+cover": "coverage",
    r"fmt\s*:\s*(?:off|skip)": "ruff format",
    r"isort\s*:\s*skip": "ruff",
})
TYPESCRIPT_MARKERS = FrozenOrderedDict({
    r"@ts-(?:ignore|expect-error|nocheck)": "tsc",
    r"Stryker\s+(?:disable|restore)": "Stryker",
    r"(?:c8|istanbul|node:coverage)\s+ignore": "coverage",
    r"(?:es|ox)lint-(?:disable|enable)": "oxlint",
    r"prettier-ignore": "oxfmt",
})
PYTHON_OPENING = r"#\s*"
TYPESCRIPT_OPENING = r"(?://|/\*)\s*"
PYTHON_MARKER = re.compile(
    rf"{PYTHON_OPENING}(?:{'|'.join(PYTHON_MARKERS)})", re.IGNORECASE
)
TYPESCRIPT_MARKER = re.compile(
    rf"{TYPESCRIPT_OPENING}(?:{'|'.join(TYPESCRIPT_MARKERS)})"
)
REASON = re.compile(r'reason\s*=\s*"(?:[^"\\]|\\.)*"')
SUPPRESSING = re.compile(r"\b(allow|expect|skip)\b")
FORBIDDEN_ATTRIBUTES = FrozenOrderedSet((
    "allow",
    "mutants::skip",
    "rustfmt::skip",
))
LINT_FIX = (
    "silences a lint; fix: change the code so the lint passes, or, if it"
    " can't apply, `#[expect]` it with an exception for the lint and its"
    " reason"
)
ATTRIBUTE_FIXES = FrozenOrderedDict({
    "mutants::skip": (
        "hides code from cargo-mutants; fix: test the code so its mutants"
        " die, or, if they can't, a `mutation` exception with its reason"
    ),
    "rustfmt::skip": (
        "hides code from rustfmt; fix: drop it and let rustfmt format the code"
    ),
})


def is_suppression(language: str, comment: Comment) -> bool:
    if language == "python":
        return comment.kind == "line" and bool(
            PYTHON_MARKER.search(comment.text)
        )
    return language == "typescript" and bool(
        TYPESCRIPT_MARKER.search(comment.text)
    )


def silenced_tool(language: str, marker: str) -> str:
    if language == "python":
        opening, tools, flags = PYTHON_OPENING, PYTHON_MARKERS, re.IGNORECASE
    else:
        opening, tools, flags = TYPESCRIPT_OPENING, TYPESCRIPT_MARKERS, 0
    return next(
        tool
        for pattern, tool in tools.items()
        if re.search(rf"{opening}(?:{pattern})", marker, flags)
    )


def silences(tool: str) -> str:
    return (
        f"silences {tool}; fix: change the code so {tool} passes, or, if the"
        " rule can't apply, an exception for that rule with its reason"
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
            Issue(
                where,
                (
                    f"`#[expect({lint})]` silences `{lint}`; fix: change the code"
                    f" so `{lint}` passes and drop it, or, if the lint can't"
                    f" apply, a `{lint}` exception with its reason"
                ),
            )
            for lint in attribute_lints(arguments)
            if not exceptions.covers(lint, file)
        )
    elif name in FORBIDDEN_ATTRIBUTES or (
        name == "cfg_attr" and SUPPRESSING.search(arguments)
    ):
        fix = ATTRIBUTE_FIXES.get(name, LINT_FIX)
        yield Issue(where, f"`#[{name}{arguments}]` {fix}")


def suppressions(
    language: str, sources: Mapping[str, Source], exceptions: Exceptions
) -> Iterator[Issue]:
    for file, source in sources.items():
        for attribute in source.attributes:
            yield from attribute_issue(file, attribute, exceptions)
        yield from (
            Issue(
                f"{file}:{line}",
                f"`{marker}` {silences(silenced_tool(language, marker))}",
            )
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
