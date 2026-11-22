import json
import tomllib
from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.values import entries, lookup, parse_toml, strings, table

DEV = FrozenOrderedSet(("dev-dependencies", "dev_dependencies"))
BUILT = FrozenList(("dependencies", "build-dependencies", "build_dependencies"))
INHERITED = FrozenOrderedSet(("dependencies", "lints"))


@dataclass(frozen=True, slots=True)
class Edge:
    package: str
    built: bool


def parsed(text: str | None) -> Mapping[str, object] | None:
    if text is None:
        return None
    try:
        return parse_toml(text)
    except tomllib.TOMLDecodeError:
        return None


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def fields(
    data: Mapping[str, object], prefix: str, skipped: FrozenOrderedSet[str]
) -> FrozenList[str]:
    return FrozenList(
        f"{prefix}{key}={canonical(value)}"
        for key, value in sorted(data.items())
        if key not in skipped
    )


def targets(
    manifest: Mapping[str, object],
) -> FrozenList[tuple[str, Mapping[str, object]]]:
    return FrozenList(
        (str(name), table(spec))
        for name, spec in sorted(table(manifest.get("target")).items())
    )


def published(manifest: Mapping[str, object]) -> FrozenList[str]:
    """A manifest as its dependents build against it: without dev-dependencies."""
    top = fields(manifest, "", DEV | FrozenOrderedSet(("target",)))
    return top + FrozenList(
        line
        for name, spec in targets(manifest)
        for line in fields(spec, f"target.{name}.", DEV)
    )


def shared(root: Mapping[str, object]) -> FrozenList[str]:
    workspace = table(root.get("workspace"))
    return fields(root, "", FrozenOrderedSet(("workspace",))) + fields(
        workspace, "workspace.", INHERITED
    )


def dependency_tables(
    manifest: Mapping[str, object], *, dev: bool
) -> FrozenList[Mapping[str, object]]:
    names = BUILT + FrozenList(DEV) if dev else BUILT
    sources = FrozenList((manifest, *(spec for _, spec in targets(manifest))))
    return FrozenList(
        table(source.get(name)) for source in sources for name in names
    )


def inherited(
    manifest: Mapping[str, object], root: Mapping[str, object], *, dev: bool
) -> FrozenList[str]:
    available = table(lookup(root, "workspace.dependencies"))
    names = FrozenOrderedSet(
        sorted(
            name
            for dependencies in dependency_tables(manifest, dev=dev)
            for name, spec in dependencies.items()
            if table(spec).get("workspace") is True
        )
    )
    return FrozenList(
        f"dependency {name}={canonical(available.get(name))}" for name in names
    )


def linted(
    manifest: Mapping[str, object], root: Mapping[str, object]
) -> FrozenList[str]:
    if lookup(manifest, "lints.workspace") is not True:
        return FrozenList()
    return FrozenList((f"lints={canonical(lookup(root, 'workspace.lints'))}",))


def built(dependency: Mapping[str, object]) -> bool:
    kinds = entries(dependency.get("dep_kinds"))
    return not kinds or any(table(kind).get("kind") != "dev" for kind in kinds)


def graph(
    metadata: Mapping[str, object],
) -> FrozenOrderedDict[str, FrozenList[Edge]]:
    nodes = FrozenList(map(table, entries(lookup(metadata, "resolve.nodes"))))
    return FrozenOrderedDict(
        (
            str(node.get("id")),
            FrozenList(
                Edge(str(dependency.get("pkg")), built(dependency))
                for dependency in map(table, entries(node.get("deps")))
            ),
        )
        for node in nodes
    )


def grow(
    found: FrozenOrderedSet[str],
    fresh: FrozenOrderedSet[str],
    edges: Mapping[str, Sequence[Edge]],
) -> FrozenOrderedSet[str]:
    more = FrozenOrderedSet(
        edge.package
        for node in fresh
        for edge in edges.get(node, FrozenList())
        if edge.built and edge.package not in found
    )
    return grow(found | more, more, edges) if more else found


def reached(
    start: str, edges: Mapping[str, Sequence[Edge]]
) -> FrozenOrderedSet[str]:
    """A package's own edges of every kind, then what they build against."""
    first = FrozenOrderedSet(
        edge.package for edge in edges.get(start, FrozenList())
    )
    return grow(first, first, edges)


def described(package: Mapping[str, object], features: str) -> str:
    source = package.get("source") or "path"
    return f"{package.get('name')} {package.get('version')} {source} {features}"


def locked(
    metadata: Mapping[str, object],
) -> FrozenOrderedDict[str, FrozenList[str]] | None:
    if "resolve" not in metadata:
        return None
    members = FrozenOrderedSet(strings(metadata.get("workspace_members")))
    packages = FrozenOrderedDict(
        (str(package.get("id")), package)
        for package in map(table, entries(metadata.get("packages")))
    )
    features = FrozenOrderedDict(
        (str(node.get("id")), ",".join(strings(node.get("features"))))
        for node in map(table, entries(lookup(metadata, "resolve.nodes")))
    )
    edges = graph(metadata)
    return FrozenOrderedDict(
        (
            str(table(packages.get(member)).get("name")),
            FrozenList(
                sorted(
                    described(
                        table(packages.get(other)), features.get(other, "")
                    )
                    for other in reached(member, edges)
                    if other not in members
                )
            ),
        )
        for member in members
    )
