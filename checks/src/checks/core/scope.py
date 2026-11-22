from dataclasses import dataclass, field
from pathlib import PurePosixPath
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.rust_layers import packages_of
from checks.core.values import entries, matches, normalized, posix, table

DOCS = FrozenList((
    "**/*.md",
    "docs/**",
    "**/LICENSE*",
    "**/COPYING*",
    ".github/**",
))


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    path: str
    dependencies: FrozenList[str] = field(default_factory=FrozenList)


def folder(path: str) -> str:
    return normalized(str(PurePosixPath(posix(path)).parent))


def inside(path: str, root: str) -> str:
    whole = PurePosixPath(path)
    if not whole.is_relative_to(root):
        return whole.as_posix()
    relative = whole.relative_to(root).as_posix()
    return "" if relative == "." else relative


def workspace(metadata: Mapping[str, object]) -> FrozenList[Package]:
    root = normalized(str(metadata.get("workspace_root")))
    members = packages_of(metadata)
    folders = FrozenOrderedDict(
        (folder(str(member.get("manifest_path"))), str(member.get("name")))
        for member in members
    )
    return FrozenList(
        Package(
            str(member.get("name")),
            inside(folder(str(member.get("manifest_path"))), root),
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


def any_match(file: str, globs: Sequence[str]) -> bool:
    return any(matches(file, glob) for glob in globs)


def owned(file: str, packages: Sequence[Package]) -> str:
    package = owner(file, packages)
    return package.name if package else ""


def dependents(
    names: FrozenOrderedSet[str], packages: Sequence[Package]
) -> FrozenOrderedSet[str]:
    more = FrozenOrderedSet(
        package.name
        for package in packages
        if package.name not in names
        and any(dependency in names for dependency in package.dependencies)
    )
    return dependents(names | more, packages) if more else names


def dependencies(
    names: FrozenOrderedSet[str], packages: Sequence[Package]
) -> FrozenOrderedSet[str]:
    more = FrozenOrderedSet(
        dependency
        for package in packages
        if package.name in names
        for dependency in package.dependencies
        if dependency not in names
    )
    return dependencies(names | more, packages) if more else names
