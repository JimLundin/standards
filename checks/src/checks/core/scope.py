from dataclasses import dataclass, field
from pathlib import PurePosixPath
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core import suites
from checks.core.rust_layers import packages_of
from checks.core.suites import Changes
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    matches,
    normalized,
    operands,
    options,
    parse_json,
    posix,
    table,
)

SHARED = FrozenList(("exceptions.toml", suites.SUITES))
GLOBAL = FrozenOrderedDict({
    "python": FrozenList((
        "**/pyproject.toml",
        "uv.lock",
        ".python-version",
        ".importlinter",
    )),
    "rust": FrozenList((
        "**/Cargo.toml",
        "Cargo.lock",
        "rust-toolchain",
        "rust-toolchain.toml",
        "clippy.toml",
        ".clippy.toml",
        "rustfmt.toml",
        ".rustfmt.toml",
        ".cargo/**",
        ".config/**",
    )),
    "typescript": FrozenList((
        "**/package.json",
        "package-lock.json",
        "**/tsconfig*.json",
        "biome.json",
        "biome.jsonc",
        "knip.json",
        "stryker.conf*",
        "stryker.config.*",
        ".npmrc",
    )),
})
DOCS = FrozenList((
    "**/*.md",
    "docs/**",
    "**/LICENSE*",
    "**/COPYING*",
    ".github/**",
))
PACKAGE_SOURCES = FrozenList(("**/*.rs", "**/*.md"))


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    path: str
    dependencies: FrozenList[str] = field(default_factory=FrozenList)


@dataclass(frozen=True, slots=True)
class Forced:
    everything: str = ""
    whole: str = ""


@dataclass(frozen=True, slots=True)
class Scope:
    mode: str
    reason: str = ""
    packages: FrozenList[str] = field(default_factory=FrozenList)


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


def is_global(language: str, file: str) -> bool:
    return any_match(file, (*SHARED, *GLOBAL[language]))


def owned(file: str, packages: Sequence[Package]) -> str:
    package = owner(file, packages)
    if package is None or not any_match(file, PACKAGE_SOURCES):
        return ""
    return package.name


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


def scope(
    language: str,
    changed: Sequence[str],
    packages: Sequence[Package],
    forced: Forced,
) -> Scope:
    everything = FrozenList(package.name for package in packages)
    trigger = next((file for file in changed if is_global(language, file)), "")
    if forced.everything or trigger:
        reason = forced.everything or f"{trigger} changed"
        return Scope("all", reason, everything)
    if forced.whole:
        return Scope("whole", forced.whole, everything)
    loose = FrozenList(file for file in changed if not owned(file, packages))
    unowned = next((file for file in loose if not any_match(file, DOCS)), "")
    if unowned:
        return Scope("whole", f"{unowned} changed", everything)
    names = FrozenOrderedSet(
        name for file in changed if (name := owned(file, packages))
    )
    if names:
        affected = dependents(names, packages)
        return Scope(
            "packages",
            packages=FrozenList(
                name for name in everything if name in affected
            ),
        )
    return Scope("docs" if changed else "none")


def summary(result: Scope, total: int) -> str:
    match result.mode:
        case "all":
            return f"everything: {result.reason}"
        case "whole":
            return f"whole project: {result.reason}"
        case "packages":
            count = len(result.packages)
            return f"{count} of {total} packages: {', '.join(result.packages)}"
        case "docs":
            return "docs only: build and test steps skipped"
        case _:
            return "no changes: build and test steps skipped"


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    changed = operands(arguments)[2]
    return Request(
        FrozenList((changed, suites.SUITES, *options(arguments, "--metadata=")))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, tier, changed_list = operands(arguments)
    metadata = options(arguments, "--metadata=")
    packages = (
        workspace(parse_json(inputs.texts.get(metadata[0])))
        if metadata
        else FrozenList()
    )
    forced = Forced(
        next(iter(options(arguments, "--all=")), ""),
        next(iter(options(arguments, "--whole=")), ""),
    )
    changed = FrozenList(
        posix(line)
        for line in inputs.texts.get(changed_list, "").splitlines()
        if line
    )
    result = scope(language, changed, packages, forced)
    names = FrozenList(package.name for package in packages)
    loaded = suites.load(inputs.texts.get(suites.SUITES), language, names)
    changes = Changes(changed, result.packages, everything=result.mode == "all")
    chosen = suites.triggered(loaded.entries, tier, changes)
    listed = result.packages if result.mode == "packages" else FrozenList()
    return Outcome(
        FrozenList((
            f"mode\t{result.mode}",
            f"summary\t{summary(result, len(packages))}",
            *(f"package\t{name}" for name in listed),
            *(f"suite\t{suite.name}\t{suite.command}" for suite in chosen),
            *(f"problem\t{problem}" for problem in loaded.problems),
        )),
        1 if loaded.problems else 0,
    )
