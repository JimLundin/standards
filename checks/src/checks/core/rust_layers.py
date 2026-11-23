import json
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedSet

from checks.core.cargo import (
    core_packages,
    is_shell,
    layer,
    packages_of,
    relative,
    target_kinds,
)
from checks.core.values import Inputs, Outcome, Request, listing, parse_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LAYERS = FrozenOrderedSet(("core", "shell"))
LAYER = "package.metadata.standards.layer"
USE = 'use "core" or "shell"'
CORELESS = "has binaries but no no_std library to hold the pure core"


def manifest(root: str, package: Mapping[str, object]) -> str:
    return relative(str(package.get("manifest_path")), root)


def valid(declared: object) -> bool:
    return isinstance(declared, str) and declared in LAYERS


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
        str(package.get("name")) for package in core_packages(packages)
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
