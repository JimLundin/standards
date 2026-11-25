import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.cargo import (
    Library,
    core_packages,
    library_of,
    packages_of,
    relative,
)
from checks.core.exceptions import BOX, EXCEPTIONS, Exceptions, exceptions_in
from checks.core.rust_api import Finding
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    is_table,
    normalized,
    parse_json,
    parse_toml,
    summarized,
    table,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

POINTERS = FrozenList((
    "alloc::boxed::Box",
    "alloc::rc::Rc",
    "alloc::rc::Weak",
    "alloc::sync::Arc",
    "alloc::sync::Weak",
))
PLAIN = "the core holds plain values: keep a recursive type's parts in a Vec and refer to them by index"
DISALLOWED = "clippy::disallowed_types"
QUOTED = re.compile(r"`([^`]+)`")
NO_STD = re.compile(r"#!\[(?:no_std|cfg_attr\(not\(test\),\s*no_std\))\]")
STD = re.compile(r"\bextern\s+crate\s+std\b")
TEST_ONLY = "#[cfg(test)]"
UNCONDITIONAL = "declare `#![no_std]` unconditionally; the core does no I/O"
TESTS_ONLY = f"`extern crate std` outside `{TEST_ONLY}`; the core does no I/O"
# A JSON string is a TOML basic string, but only unescaped: TOML has no
# surrogate pairs for characters outside the basic multilingual plane.
STRING = json.JSONEncoder(ensure_ascii=False)


def toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if is_table(value):
        pairs = ", ".join(
            f"{STRING.encode(key)} = {toml_value(item)}"
            for key, item in value.items()
        )
        return f"{{ {pairs} }}"
    if isinstance(value, Sequence) and not isinstance(value, str):
        return f"[{', '.join(toml_value(item) for item in value)}]"
    return STRING.encode(str(value))


def disallowed_path(item: object) -> str:
    return item if isinstance(item, str) else str(table(item).get("path"))


def core_config(base: Mapping[str, object]) -> str:
    listed = entries(base.get("disallowed-types"))
    known = FrozenList(disallowed_path(item) for item in listed)
    added = FrozenList(
        {"path": pointer, "reason": PLAIN}
        for pointer in POINTERS
        if pointer not in known
    )
    merged = FrozenOrderedDict({
        **base,
        "disallowed-types": FrozenList((*listed, *added)),
    })
    return "".join(
        f"{json.dumps(key)} = {toml_value(value)}\n"
        for key, value in merged.items()
    )


def clippy_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList(arguments[:1]))


def clippy_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    base, written = arguments
    config = core_config(parse_toml(inputs.texts.get(base)))
    return Outcome(writes=FrozenOrderedDict({written: config}))


def libraries(metadata: Mapping[str, object]) -> FrozenList[Library]:
    root = str(metadata.get("workspace_root"))
    return FrozenList(
        library
        for package in core_packages(packages_of(metadata))
        for library in library_of(package, root)
    )


def core_files(
    found: Sequence[Library], files: Sequence[str]
) -> FrozenList[str]:
    return FrozenList(
        file for file in files if any(library.holds(file) for library in found)
    )


def code_lines(source: str) -> FrozenList[str]:
    return FrozenList(
        line.partition("//")[0].strip() for line in source.splitlines()
    )


def std_findings(path: str, source: str) -> Iterator[Finding]:
    code = FrozenList(
        (number, line)
        for number, line in enumerate(code_lines(source), start=1)
        if line
    )
    for index, (number, line) in enumerate(code):
        before = FrozenList(previous for _, previous in code[index - 1 : index])
        if (
            STD.search(line)
            and not line.startswith(TEST_ONLY)
            and TEST_ONLY not in before
        ):
            yield Finding(path, number, TESTS_ONLY)


def source_findings(
    found: Sequence[Library], files: Sequence[str], texts: Mapping[str, str]
) -> Iterator[Finding]:
    for library in found:
        root = texts.get(library.root)
        if root is not None and not any(
            NO_STD.fullmatch(line) for line in code_lines(root)
        ):
            yield Finding(library.root, 1, UNCONDITIONAL)
    for file in core_files(found, files):
        yield from std_findings(file, text(texts, file))


def primary(message: Mapping[str, object], root: str) -> Finding | None:
    spans = FrozenList(
        span
        for span in map(table, entries(message.get("spans")))
        if span.get("is_primary") is True
    )
    if not spans:
        return None
    path = relative(str(spans[0].get("file_name")), root)
    line = spans[0].get("line_start")
    return Finding(path, line if isinstance(line, int) else 0)


def pointer_of(message: Mapping[str, object]) -> str:
    code = str(table(message.get("code")).get("code"))
    named = QUOTED.search(str(message.get("message")))
    if code != DISALLOWED or named is None or named[1] not in POINTERS:
        return ""
    return named[1]


def diagnostic_finding(
    record: Mapping[str, object],
    sources: Sequence[str],
    root: str,
    exceptions: Exceptions,
) -> Finding | None:
    message = table(record.get("message"))
    where = primary(message, root)
    if record.get("reason") != "compiler-message" or where is None:
        return None
    target = str(table(record.get("target")).get("src_path"))
    if message.get("level") == "error":
        # rustc places errors without a source, like a missing `std`,
        # in whichever file it loaded first.
        located = (
            where
            if where.path.endswith(".rs")
            else Finding(relative(target, root), 1)
        )
        return replace(located, message=str(message.get("message")))
    pointer = pointer_of(message)
    source = normalized(target)
    if (
        not pointer
        or source not in sources
        or exceptions.covers(BOX, where.path)
    ):
        return None
    return replace(where, message=f"uses `{pointer}`; {PLAIN}")


def diagnostic_findings(
    text: str, found: Sequence[Library], root: str, exceptions: Exceptions
) -> Iterator[Finding]:
    sources = FrozenList(library.source for library in found)
    for line in text.splitlines():
        if line.startswith("{"):
            finding = diagnostic_finding(
                parse_json(line), sources, root, exceptions
            )
            if finding is not None:
                yield finding


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    metadata_path, diagnostics, *files = arguments
    fixed = FrozenList((EXCEPTIONS, metadata_path, diagnostics))
    if metadata_path not in inputs.texts:
        return Request(fixed)
    found = libraries(parse_json(inputs.texts[metadata_path]))
    roots = FrozenList(library.root for library in found)
    return Request(
        FrozenList(dict.fromkeys((*fixed, *roots, *core_files(found, files))))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata_path, diagnostics, *files = arguments
    metadata = parse_json(inputs.texts.get(metadata_path))
    found = libraries(metadata)
    root = str(metadata.get("workspace_root"))
    findings = (
        *source_findings(found, files, inputs.texts),
        *diagnostic_findings(
            text(inputs.texts, diagnostics), found, root, exceptions_in(inputs)
        ),
    )
    names = " ".join(dict.fromkeys(library.name for library in found))
    return summarized(
        FrozenList(
            f"{finding.path}:{finding.line}: {finding.message}"
            for finding in sorted(
                dict.fromkeys(findings),
                key=lambda f: (f.path, f.line, f.message),
            )
        ),
        f"no_std: {names}" if names else "no libraries",
    )
