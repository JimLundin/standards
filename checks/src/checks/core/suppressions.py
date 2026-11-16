import re
from functools import partial
from tokenize import COMMENT, TokenError, generate_tokens
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.waivers import Issue, Waiver, waived

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

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
    r"biome-ignore",
    r"@ts-(?:ignore|expect-error|nocheck)",
    r"Stryker\s+(?:disable|restore)",
    r"(?:c8|istanbul|node:coverage)\s+ignore",
    r"eslint-disable",
    r"prettier-ignore",
))
PYTHON_MARKER = re.compile(
    rf"#\s*(?:{'|'.join(PYTHON_MARKERS)})", re.IGNORECASE
)
TYPESCRIPT_MARKER = re.compile(
    rf"(?://|/\*)\s*(?:{'|'.join(TYPESCRIPT_MARKERS)})"
)
RUST_ATTRIBUTE = re.compile(
    r"#!?\[\s*(?P<name>[a-z_]+(?:::[a-z_]+)?)\s*(?P<args>\((?:[^()]|\([^()]*\))*\))?\s*\]"
)
REASON = re.compile(r'reason\s*=\s*"(?:[^"\\]|\\.)*"')
SUPPRESSING = re.compile(r"\b(allow|expect|skip)\b")
FORBIDDEN_ATTRIBUTES = FrozenOrderedSet((
    "allow",
    "mutants::skip",
    "rustfmt::skip",
))
SOURCES = FrozenOrderedDict({
    "python": FrozenList((".py", ".pyw")),
    "rust": FrozenList((".rs",)),
    "typescript": FrozenList((
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".js",
        ".jsx",
        ".mjs",
    )),
})
INSTEAD = "; add an entry to exceptions.toml instead"


def is_source(language: str, file: str) -> bool:
    return file.endswith(tuple(SOURCES.get(language, FrozenList())))


def python_markers(text: str) -> Iterator[tuple[int, str]]:
    lines = iter(text.splitlines(keepends=True))
    try:
        tokens = FrozenList(generate_tokens(partial(next, lines, "")))
    except SyntaxError, TokenError:
        return
    yield from (
        (token.start[0], token.string.strip())
        for token in tokens
        if token.type == COMMENT and PYTHON_MARKER.search(token.string)
    )


def typescript_markers(text: str) -> Iterator[tuple[int, str]]:
    yield from (
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if TYPESCRIPT_MARKER.search(line)
    )


def attribute_lints(arguments: str) -> FrozenList[str]:
    inner = REASON.sub("", arguments.strip()[1:-1])
    return FrozenList(part.strip() for part in inner.split(",") if part.strip())


def rust_attributes(text: str) -> Iterator[tuple[int, str, str]]:
    for match in RUST_ATTRIBUTE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        yield line, match["name"], match["args"] or ""


def rust_issues(
    file: str, text: str, waivers: Sequence[Waiver]
) -> Iterator[Issue]:
    for line, name, arguments in rust_attributes(text):
        where = f"{file}:{line}"
        if name == "expect":
            yield from (
                Issue(where, f"#[expect({lint})] is not in exceptions.toml")
                for lint in attribute_lints(arguments)
                if not waived(waivers, file, lint)
            )
        elif name in FORBIDDEN_ATTRIBUTES or (
            name == "cfg_attr" and SUPPRESSING.search(arguments)
        ):
            yield Issue(where, f"#[{name}{arguments}]{INSTEAD}")


def suppressions(
    language: str, texts: Mapping[str, str], waivers: Sequence[Waiver]
) -> Iterator[Issue]:
    for file, text in texts.items():
        if not is_source(language, file):
            continue
        if language == "rust":
            yield from rust_issues(file, text, waivers)
            continue
        scan = python_markers if language == "python" else typescript_markers
        yield from (
            Issue(f"{file}:{line}", f"suppression `{marker}`{INSTEAD}")
            for line, marker in scan(text)
        )


def used_attributes(
    texts: Mapping[str, str],
) -> FrozenOrderedSet[tuple[str, str]]:
    return FrozenOrderedSet(
        (file, lint)
        for file, text in texts.items()
        if file.endswith(".rs")
        for _, name, arguments in rust_attributes(text)
        if name == "expect"
        for lint in attribute_lints(arguments)
    )
