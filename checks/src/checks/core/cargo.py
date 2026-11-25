"""The workspace as `cargo metadata` describes it."""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
lazy from collections.abc import Iterator, Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.values import entries, lookup, normalized, strings, table

LIBRARY_KINDS = FrozenOrderedSet(("lib", "rlib"))
BINARY = "bin"


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    path: str
    dependencies: FrozenList[str] = field(default_factory=FrozenList)


@dataclass(frozen=True, slots=True)
class Library:
    name: str
    root: str
    source: str

    def holds(self, file: str) -> bool:
        return file.endswith(".rs") and PurePosixPath(file).is_relative_to(
            folder(self.root)
        )

    def cedes(self, file: str, binary: str) -> bool:
        inner = folder(binary)
        return file == binary or (
            inner != folder(self.root)
            and PurePosixPath(file).is_relative_to(inner)
        )


def relative(path: str, root: str) -> str:
    """A path relative to the root, "" for the root itself, or whole outside it."""
    whole, base = PurePosixPath(normalized(path)), normalized(root)
    if not whole.is_relative_to(base):
        return whole.as_posix()
    inner = whole.relative_to(base).as_posix()
    return "" if inner == "." else inner


def folder(path: str) -> str:
    return PurePosixPath(normalized(path)).parent.as_posix()


def packages_of(
    metadata: Mapping[str, object],
) -> FrozenList[Mapping[str, object]]:
    return FrozenList(map(table, entries(metadata.get("packages"))))


def targets_of(
    package: Mapping[str, object],
) -> FrozenList[Mapping[str, object]]:
    return FrozenList(map(table, entries(package.get("targets"))))


def kinds(target: Mapping[str, object]) -> FrozenList[str]:
    return strings(target.get("kind"))


def is_library(target: Mapping[str, object]) -> bool:
    return any(kind in LIBRARY_KINDS for kind in kinds(target))


def library_of(package: Mapping[str, object], root: str) -> Iterator[Library]:
    for target in filter(is_library, targets_of(package)):
        source = str(target.get("src_path"))
        yield Library(
            str(package.get("name")), relative(source, root), normalized(source)
        )


def library_files(
    metadata: Mapping[str, object], files: Sequence[str]
) -> FrozenOrderedSet[str]:
    root = str(metadata.get("workspace_root"))
    packages = packages_of(metadata)
    found = FrozenList(
        library for package in packages for library in library_of(package, root)
    )
    binaries = FrozenList(
        relative(str(target.get("src_path")), root)
        for package in packages
        for target in targets_of(package)
        if BINARY in kinds(target)
    )
    return FrozenOrderedSet(
        file
        for file in files
        if any(
            library.holds(file)
            and not any(library.cedes(file, binary) for binary in binaries)
            for library in found
        )
    )


def target_kinds(package: Mapping[str, object]) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        kind for target in targets_of(package) for kind in kinds(target)
    )


def layer(package: Mapping[str, object]) -> object:
    declared = lookup(package, "metadata.standards.layer")
    return "core" if declared is None else declared


def is_shell(package: Mapping[str, object]) -> bool:
    return layer(package) == "shell"


def core_packages(
    packages: Sequence[Mapping[str, object]],
) -> FrozenList[Mapping[str, object]]:
    return FrozenList(
        package
        for package in packages
        if any(map(is_library, targets_of(package))) and not is_shell(package)
    )


def workspace(metadata: Mapping[str, object]) -> FrozenList[Package]:
    root = str(metadata.get("workspace_root"))
    members = packages_of(metadata)
    folders = FrozenOrderedDict(
        (folder(str(member.get("manifest_path"))), str(member.get("name")))
        for member in members
    )
    return FrozenList(
        Package(
            str(member.get("name")),
            relative(folder(str(member.get("manifest_path"))), root),
            FrozenList(
                folders[path]
                for dependency in entries(member.get("dependencies"))
                if (path := normalized(str(table(dependency).get("path"))))
                in folders
            ),
        )
        for member in members
    )


def owner(file: str, packages: Sequence[Package]) -> Package | None:
    owners = FrozenList(
        package
        for package in packages
        if not package.path or file.startswith(f"{package.path}/")
    )
    return max(owners, key=lambda package: len(package.path), default=None)


def owned(file: str, packages: Sequence[Package]) -> str:
    package = owner(file, packages)
    return package.name if package else ""


def reach(
    names: FrozenOrderedSet[str], edges: Mapping[str, Sequence[str]]
) -> FrozenOrderedSet[str]:
    """The names and every name their edges lead to, in the order found."""
    more = FrozenOrderedSet(
        other
        for name in names
        for other in edges.get(name, ())
        if other not in names
    )
    return reach(names | more, edges) if more else names


def dependencies(
    names: FrozenOrderedSet[str], packages: Sequence[Package]
) -> FrozenOrderedSet[str]:
    return reach(
        names,
        FrozenOrderedDict(
            (package.name, package.dependencies) for package in packages
        ),
    )


def dependents(
    names: FrozenOrderedSet[str], packages: Sequence[Package]
) -> FrozenOrderedSet[str]:
    return reach(
        names,
        FrozenOrderedDict(
            (
                package.name,
                FrozenList(
                    other.name
                    for other in packages
                    if package.name in other.dependencies
                ),
            )
            for package in packages
        ),
    )
