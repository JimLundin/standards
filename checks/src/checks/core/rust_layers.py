import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    listing,
    lookup,
    parse_json,
    posix,
    strings,
    table,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LIBRARY_KINDS = FrozenOrderedSet(("lib", "rlib"))
LAYERS = FrozenOrderedSet(("core", "shell"))
LAYER = "package.metadata.standards.layer"
USE = 'use "core" or "shell"'
CORELESS = "has binaries but no no_std library to hold the pure core"


def target_kinds(package: Mapping[str, object]) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        kind
        for target in entries(package.get("targets"))
        for kind in strings(table(target).get("kind"))
    )


def manifest(root: str, package: Mapping[str, object]) -> str:
    path = PurePosixPath(posix(str(package.get("manifest_path"))))
    return path.relative_to(posix(root)).as_posix()


def layer(package: Mapping[str, object]) -> object:
    declared = lookup(package, "metadata.standards.layer")
    return "core" if declared is None else declared


def valid(declared: object) -> bool:
    return isinstance(declared, str) and declared in LAYERS


def is_shell(package: Mapping[str, object]) -> bool:
    return layer(package) == "shell"


def packages_of(
    metadata: Mapping[str, object],
) -> FrozenList[Mapping[str, object]]:
    return FrozenList(table(item) for item in entries(metadata.get("packages")))


def layer_issues(
    root: str, packages: Sequence[Mapping[str, object]]
) -> FrozenList[str]:
    return FrozenList(
        f"{manifest(root, package)}: {LAYER} is {json.dumps(layer(package))}; {USE}"
        for package in packages
        if not valid(layer(package))
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((arguments[0],)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata = parse_json(inputs.texts.get(arguments[0]))
    root = str(metadata.get("workspace_root"))
    packages = packages_of(metadata)
    libraries = FrozenList(
        str(package.get("name"))
        for package in packages
        if target_kinds(package) & LIBRARY_KINDS and not is_shell(package)
    )
    coreless = FrozenList(
        f"{manifest(root, package)}: {CORELESS}"
        for package in packages
        if not libraries
        and "bin" in target_kinds(package)
        and not is_shell(package)
    )
    issues = (*layer_issues(root, packages), *coreless)
    if issues:
        return Outcome(FrozenList(issues), 1)
    return listing(libraries)
