import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

FORMATS = frozenset({61})
ALLOWED = frozenset({
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
})
ONLY_DATA = "; the core's public API takes only data"
OWNERS = ("struct", "enum", "union", "trait", "type_alias", "impl")


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
        segments = tuple(
            segment
            for segment in entries(entry.get("path"))
            if isinstance(segment, str)
        )
        return "::".join(segments) or str(reference.get("path"))

    def is_local(self, reference: Mapping[str, object]) -> bool:
        item = table(self.index.get(str(reference.get("id"))))
        return item.get("crate_id") == 0


def table(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return cast("Mapping[str, object]", value)
    return MappingProxyType({})


def entries(value: object) -> tuple[object, ...]:
    if isinstance(value, list):
        return tuple(cast("Iterable[object]", value))
    return ()


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
    line = begin[0] if begin and isinstance(begin[0], int) else 0
    return str(span.get("filename", "?")), line


def foreign_methods(crate: Crate) -> frozenset[str]:
    return frozenset(
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


def crate_findings(document: Mapping[str, object]) -> tuple[Finding, ...]:
    version = document.get("format_version")
    if version not in FORMATS:
        message = (
            f"rustdoc JSON format {version} is untested; check api.py "
            "against it and add it to FORMATS"
        )
        return (Finding("api.py", 0, message),)
    crate = Crate(table(document.get("index")), table(document.get("paths")))
    excluded = foreign_methods(crate)
    return tuple(
        finding
        for key, value in crate.index.items()
        if key not in excluded
        for item in (table(value),)
        if item.get("crate_id") == 0 and not skipped_impl(item)
        for finding in item_findings(item, crate)
    )


def documents(
    metadata: Mapping[str, object], packages: Iterable[str]
) -> tuple[Path, ...]:
    folder = Path(str(metadata.get("target_directory"))) / "doc"
    wanted = frozenset(packages)
    return tuple(
        folder / f"{str(table(target).get('name')).replace('-', '_')}.json"
        for package in entries(metadata.get("packages"))
        if table(package).get("name") in wanted
        for target in entries(table(package).get("targets"))
        if {"lib", "rlib"}
        & {str(kind) for kind in entries(table(target).get("kind"))}
    )


def read_json(path: Path) -> Mapping[str, object]:
    return table(cast("object", json.loads(path.read_text(encoding="utf-8"))))


def report(arguments: tuple[str, ...]) -> tuple[str, ...]:
    skips = tuple(
        argument.removeprefix("--skip=")
        for argument in arguments
        if argument.startswith("--skip=")
    )
    metadata_path, *packages = (
        argument for argument in arguments if not argument.startswith("--")
    )
    metadata = read_json(Path(metadata_path))
    findings = (
        finding
        for document in documents(metadata, packages)
        for finding in crate_findings(read_json(document))
    )
    return tuple(
        f"{finding.path}:{finding.line}: {finding.message}{ONLY_DATA}"
        for finding in sorted(
            set(findings), key=lambda f: (f.path, f.line, f.message)
        )
        if not any(
            PurePosixPath(finding.path).full_match(glob) for glob in skips
        )
    )


def main() -> int:
    lines = report(tuple(sys.argv[1:]))
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    output = "".join(f"{line}\n" for line in (*lines, summary))
    _ = sys.stdout.write(output)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
