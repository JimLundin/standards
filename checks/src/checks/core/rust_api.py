from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    matches,
    operands,
    options,
    parse_json,
    posix,
    summarized,
    table,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

FORMATS = FrozenOrderedSet((61,))
ALLOWED = FrozenOrderedSet((
    "core::borrow::Borrow",
    "core::clone::Clone",
    "core::cmp::Eq",
    "core::cmp::Ord",
    "core::cmp::PartialEq",
    "core::cmp::PartialOrd",
    "core::convert::AsRef",
    "core::convert::From",
    "core::convert::Into",
    "core::convert::TryFrom",
    "core::convert::TryInto",
    "core::default::Default",
    "core::fmt::Debug",
    "core::fmt::Display",
    "core::hash::Hash",
    "core::marker::Copy",
    "core::marker::Send",
    "core::marker::Sized",
    "core::marker::Sync",
))
ONLY_DATA = "; the core's public API takes only data"
OWNERS = FrozenList(("struct", "enum", "union", "trait", "type_alias", "impl"))


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class Crate:
    index: Mapping[str, object]
    paths: Mapping[str, object]

    def trait_name(self, reference: Mapping[str, object]) -> str:
        entry = table(self.paths.get(str(reference.get("id"))))
        segments = FrozenList(
            segment
            for segment in entries(entry.get("path"))
            if isinstance(segment, str)
        )
        return "::".join(segments) or str(reference.get("path"))

    def is_local(self, reference: Mapping[str, object]) -> bool:
        item = table(self.index.get(str(reference.get("id"))))
        return item.get("crate_id") == 0


def problems(node: object, crate: Crate) -> Iterator[str]:
    fields = table(node)
    if "dyn_trait" in fields:
        traits = entries(table(fields["dyn_trait"]).get("traits"))
        names = ", ".join(
            crate.trait_name(table(table(bound).get("trait")))
            for bound in traits
        )
        yield f"takes a trait object `dyn {names}`"
        return
    if "function_pointer" in fields:
        yield "takes a function pointer"
        return
    if "trait_bound" in fields:
        reference = table(table(fields["trait_bound"]).get("trait"))
        name = crate.trait_name(reference)
        if name not in ALLOWED:
            yield f"is bounded by `{name}`"
    for value in (*fields.values(), *entries(node)):
        yield from problems(value, crate)


def location(item: Mapping[str, object]) -> tuple[str, int]:
    span = table(item.get("span"))
    begin = entries(span.get("begin"))
    first = begin[0] if begin else None
    line = first if isinstance(first, int) else 0
    return str(span.get("filename", "?")), line


def foreign_methods(crate: Crate) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        str(member)
        for item in crate.index.values()
        if table(item).get("crate_id") == 0
        for implementation in (
            table(table(table(item).get("inner")).get("impl")),
        )
        if implementation
        and (
            implementation.get("is_synthetic")
            or implementation.get("blanket_impl") is not None
            or (
                implementation.get("trait") is not None
                and not crate.is_local(table(implementation.get("trait")))
            )
        )
        for member in entries(implementation.get("items"))
    )


def item_parts(item: Mapping[str, object]) -> Iterator[object]:
    inner = table(item.get("inner"))
    function = table(inner.get("function"))
    if function:
        yield table(function.get("sig")).get("inputs")
        yield function.get("generics")
    if "struct_field" in inner:
        yield inner["struct_field"]
    for owner in OWNERS:
        details = table(inner.get(owner))
        yield details.get("generics")
        if owner == "type_alias":
            yield details.get("type")
        if owner == "impl" and details.get("trait") is not None:
            yield table(table(details.get("trait")).get("args"))


def is_async(item: Mapping[str, object]) -> bool:
    function = table(table(item.get("inner")).get("function"))
    return table(function.get("header")).get("is_async") is True


def skipped_impl(item: Mapping[str, object]) -> bool:
    implementation = table(table(item.get("inner")).get("impl"))
    return bool(
        implementation.get("is_synthetic")
        or implementation.get("blanket_impl") is not None
    )


def item_findings(
    item: Mapping[str, object], crate: Crate
) -> Iterator[Finding]:
    path, line = location(item)
    name = item.get("name") or "impl"
    messages = (
        *(("is async",) if is_async(item) else ()),
        *(
            message
            for part in item_parts(item)
            for message in problems(part, crate)
        ),
    )
    for message in dict.fromkeys(messages):
        yield Finding(path, line, f"`{name}` {message}")


def crate_findings(document: Mapping[str, object]) -> FrozenList[Finding]:
    version = document.get("format_version")
    if version not in FORMATS:
        message = (
            f"rustdoc JSON format {version} is untested; check api.py "
            "against it and add it to FORMATS"
        )
        return FrozenList((Finding("api.py", 0, message),))
    crate = Crate(table(document.get("index")), table(document.get("paths")))
    excluded = foreign_methods(crate)
    return FrozenList(
        finding
        for key, value in crate.index.items()
        if key not in excluded
        for item in (table(value),)
        if item.get("crate_id") == 0 and not skipped_impl(item)
        for finding in item_findings(item, crate)
    )


def documents(
    metadata: Mapping[str, object], packages: Sequence[str]
) -> FrozenList[str]:
    folder = f"{posix(str(metadata.get('target_directory')))}/doc"
    return FrozenList(
        f"{folder}/{str(table(target).get('name')).replace('-', '_')}.json"
        for package in entries(metadata.get("packages"))
        if table(package).get("name") in packages
        for target in entries(table(package).get("targets"))
        if any(
            kind in {"lib", "rlib"}
            for kind in entries(table(target).get("kind"))
        )
    )


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    metadata_path, *packages = operands(arguments)
    if metadata_path not in inputs.texts:
        return Request(FrozenList((metadata_path,)))
    metadata = parse_json(inputs.texts[metadata_path])
    return Request(FrozenList((metadata_path, *documents(metadata, packages))))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    skips = options(arguments, "--skip=")
    metadata_path, *packages = operands(arguments)
    metadata = parse_json(inputs.texts.get(metadata_path))
    findings = FrozenOrderedSet(
        finding
        for document in documents(metadata, packages)
        for finding in crate_findings(parse_json(inputs.texts.get(document)))
    )
    return summarized(
        FrozenList(
            f"{finding.path}:{finding.line}: {finding.message}{ONLY_DATA}"
            for finding in sorted(
                findings, key=lambda f: (f.path, f.line, f.message)
            )
            if not any(matches(finding.path, glob) for glob in skips)
        )
    )
