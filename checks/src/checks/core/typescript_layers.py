import json
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import TYPESCRIPT_PURITY, Exceptions
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    listing,
    lookup,
    matches,
    operands,
    parse_json,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class Layer(StrEnum):
    CORE = "core"
    SHELL = "shell"
    UI = "ui"


UNDECLARED = Layer.CORE
LAYER = "standards.layer"
USE = f'use "{Layer.CORE}", "{Layer.SHELL}" or "{Layer.UI}"'
# The layers outside the core, whose files the thin-shell rules measure and
# mutation testing skips.
OUTER_LAYERS = FrozenOrderedSet((Layer.SHELL, Layer.UI))

PURE = FrozenList((
    "Array",
    "Data",
    "Equal",
    "Hash",
    "Match",
    "Number",
    "Option",
    "Order",
    "Record",
    "Result",
    "Schema",
    "String",
    "Struct",
))
FUNCTIONS = FrozenList(("flow", "pipe"))
HASHED = FrozenList(("HashMap", "HashSet"))
# The definitions of an HTTP API or RPC group, without their clients and
# servers.
CONTRACTS = FrozenOrderedDict({
    "effect/http-api": FrozenList((
        "HttpApi",
        "HttpApiEndpoint",
        "HttpApiError",
        "HttpApiGroup",
        "HttpApiMiddleware",
        "HttpApiSchema",
        "HttpApiSecurity",
    )),
    "effect/rpc": FrozenList(("Rpc", "RpcGroup", "RpcMiddleware", "RpcSchema")),
})
# Tests and tool configs run beside a layer's code, not in it, as the
# standard's oxlint.config.ts names them.
TOOLING = FrozenList((
    "**/*.test.{ts,tsx}",
    "**/test/**",
    "**/*.config.{ts,tsx,mts,js,mjs}",
    "**/vitest.setup.ts",
))
CORE = (
    "the core imports only core packages, Effect's pure data modules and"
    " HTTP API and RPC definitions; another module takes a purity:<module>"
    " exception"
)
UNORDERED = "iterates in hash order: use a ReadonlyMap or a ReadonlySet"
EFFECT_HOOKS = FrozenList(("useEffect", "useLayoutEffect"))
IN_ATOMS = "an effect in a component: run it in an atom of effect/reactivity"
BROWSER = FrozenList(("window", "document", "localStorage"))
IN_BROWSER = "a browser global in a component: reach it in an atom over @effect/platform-browser"
APART = FrozenOrderedDict({
    Layer.SHELL: (
        Layer.UI,
        "the shell meets the UI only through contracts in core",
    ),
    Layer.UI: (
        Layer.SHELL,
        "the UI meets the shell only through contracts in core",
    ),
})


@dataclass(frozen=True, slots=True)
class Unknown:
    """A package whose package.json declares a layer that names none, as
    that layer's JSON."""

    folder: str
    written: str


@dataclass(frozen=True, slots=True)
class Package:
    """A package of the workspace, whose folder is "" at the root."""

    folder: str
    name: str
    layer: Layer


@dataclass(frozen=True, slots=True)
class Placement:
    file: str
    package: Package


@dataclass(frozen=True, slots=True)
class Placed:
    """Files in their packages, and the packages whose layer is unknown."""

    placements: FrozenList[Placement]
    unknown: FrozenOrderedSet[Unknown]


@dataclass(frozen=True, slots=True)
class Mapped:
    """A line of the layer map, without its package's folder."""

    layer: Layer
    path: str


def named_layer(value: object) -> Layer | None:
    return Layer(value) if value in Layer else None


def folders(file: str) -> FrozenList[str]:
    return FrozenList(
        "" if folder == PurePosixPath() else str(folder)
        for folder in PurePosixPath(file).parents
    )


def manifest(folder: str) -> str:
    return f"{folder}/package.json" if folder else "package.json"


def manifests(files: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        FrozenOrderedSet(
            manifest(folder) for file in files for folder in folders(file)
        )
    )


def package_at(texts: Mapping[str, str], folder: str) -> Package | Unknown:
    data = parse_json(texts.get(manifest(folder)))
    value = lookup(data, LAYER)
    layer = UNDECLARED if value is None else named_layer(value)
    if layer is None:
        return Unknown(folder, json.dumps(value))
    name = data.get("name")
    return Package(folder, name if isinstance(name, str) else "", layer)


def nearest(file: str, texts: Mapping[str, str]) -> str:
    return next(
        (folder for folder in folders(file) if manifest(folder) in texts), ""
    )


def placed(files: Sequence[str], texts: Mapping[str, str]) -> Placed:
    found = Placed(FrozenList(), FrozenOrderedSet())
    for file in files:
        match package_at(texts, nearest(file, texts)):
            case Package() as package:
                placements = (*found.placements, Placement(file, package))
                found = replace(found, placements=FrozenList(placements))
            case Unknown() as unknown:
                found = replace(
                    found, unknown=found.unknown | FrozenOrderedSet((unknown,))
                )
    return found


def packages_of(placed: Sequence[Placement]) -> FrozenList[Package]:
    return FrozenList(
        FrozenOrderedDict(
            (placement.package.folder, placement.package)
            for placement in placed
        ).values()
    )


def layer_issues(unknown: FrozenOrderedSet[Unknown]) -> FrozenList[str]:
    return FrozenList(
        f"{manifest(package.folder)}: {LAYER} is {package.written}; {USE}"
        for package in unknown
    )


BRACES = re.compile(r"\{([^{}]*)\}")


def alternatives(glob: str) -> FrozenList[str]:
    """The globs a glob's `{a,b}` groups stand for."""
    found = BRACES.search(glob)
    if found is None:
        return FrozenList((glob,))
    return FrozenList(
        alternative
        for choice in found[1].split(",")
        for alternative in alternatives(
            f"{glob[: found.start()]}{choice}{glob[found.end() :]}"
        )
    )


def tooling(file: str) -> bool:
    return any(
        matches(file, glob)
        for pattern in TOOLING
        for glob in alternatives(pattern)
    )


# With --code, the map holds only the layers' code, without the tests and
# tool configs that run beside it.
def mapped(arguments: Sequence[str]) -> FrozenList[str]:
    files = operands(arguments)
    if "--code" not in arguments:
        return files
    return FrozenList(file for file in files if not tooling(file))


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(manifests(mapped(arguments)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    found = placed(mapped(arguments), inputs.texts)
    if issues := layer_issues(found.unknown):
        return Outcome(issues, 1)
    return listing(
        FrozenList(
            "\t".join((
                placement.package.layer,
                placement.package.folder or ".",
                placement.file,
            ))
            for placement in found.placements
        )
    )


def mapped_line(line: str) -> FrozenList[Mapped]:
    """The line's item, or none for a line that isn't one."""
    match line.split("\t"):
        case [name, _, path] if (layer := named_layer(name)) is not None:
            return FrozenList((Mapped(layer, path),))
        case _:
            return FrozenList()


def layer_map(text: str) -> FrozenList[Mapped]:
    return FrozenList(
        item for line in text.splitlines() for item in mapped_line(line)
    )


def outer_files(text: str) -> FrozenList[str]:
    return FrozenList(
        item.path for item in layer_map(text) if item.layer in OUTER_LAYERS
    )


def within(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}/")


# A group's glob without a slash matches the last segment of any import, so
# each such module allowed is restricted again as the end of a longer one.
def anchored(name: str) -> FrozenList[str]:
    return FrozenList(() if "/" in name else (f"**/*/{name}",))


def exactly(name: str) -> FrozenList[str]:
    return FrozenList((f"!{name}", *anchored(name)))


def modules(names: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        glob
        for name in names
        for glob in (f"!{name}", f"!{name}/**", *anchored(name))
    )


def core_paths(allowed: Sequence[str]) -> FrozenList[object]:
    named = FrozenOrderedDict({
        "effect": (*PURE, *FUNCTIONS),
        "effect/Function": FUNCTIONS,
        **CONTRACTS,
    })
    kept = FrozenOrderedDict(
        (name, names)
        for name, names in named.items()
        if not any(within(name, module) for module in allowed)
    )
    # With the barrel allowed, its hash collections stay banned.
    barrel = FrozenList(
        ()
        if "effect" in kept
        else (
            {
                "name": "effect",
                "importNames": list(HASHED),
                "message": UNORDERED,
            },
        )
    )
    return FrozenList((
        *barrel,
        *(
            {"name": name, "allowImportNames": list(names), "message": CORE}
            for name, names in kept.items()
        ),
        *({"name": f"effect/{name}", "message": UNORDERED} for name in HASHED),
    ))


def core_rule(core: Sequence[str], allowed: Sequence[str]) -> object:
    group = (
        "**",
        "!./**",
        "!#*",
        "!#*/**",
        "!../**",
        *modules(core),
        *exactly("effect"),
        "!effect/Function",
        *(f"!effect/{name}" for name in HASHED),
        *(f"!{module}" for module in CONTRACTS),
        *(f"!effect/{name}" for name in PURE),
        *(
            f"!{module}/{name}"
            for module, names in CONTRACTS.items()
            for name in names
        ),
        *modules(allowed),
    )
    return {
        "paths": list(core_paths(allowed)),
        "patterns": [
            {"group": list(group), "caseSensitive": True, "message": CORE}
        ],
    }


def scoped(
    root: str, files: Sequence[str], excluded: Sequence[str], rules: str
) -> str:
    anchored_files = json.dumps([f"{root}/{glob}" for glob in files])
    anchored_excluded = json.dumps([
        f"{root}/{glob}" for glob in (*excluded, *TOOLING)
    ])
    return (
        f'\t\t{{"files": {anchored_files}, "excludeFiles": {anchored_excluded},'
        f' "rules": {rules}}},\n'
    )


def imports(rule: object) -> str:
    return json.dumps({"no-restricted-imports": ["error", rule]})


# An override replaces a rule's options, so the UI's restrictions extend the
# config's own, which `restricted` of the written config reads.
def extended(rule: str, added: Sequence[object]) -> str:
    name = json.dumps(rule)
    listed = ", ".join(map(json.dumps, added))
    return f'{name}: ["error", ...restricted({name}), {listed}]'


# The UI's bans beyond its imports: browser globals, and React's effect
# hooks read off its default or namespace import.
def ui_bans() -> str:
    globals_ = [{"message": IN_BROWSER, "name": name} for name in BROWSER]
    # Unicorn/prefer-global-this reports a read off window or self.
    properties = [
        *(
            {"message": IN_BROWSER, "object": "globalThis", "property": name}
            for name in BROWSER
        ),
        *(
            {"message": IN_ATOMS, "object": "React", "property": name}
            for name in EFFECT_HOOKS
        ),
    ]
    return (
        f"{{{extended('no-restricted-globals', globals_)},"
        f" {extended('no-restricted-properties', properties)}}}"
    )


def folder_glob(folder: str) -> str:
    return f"{folder}/**" if folder else "**"


def nested_in(package: Package, packages: Sequence[Package]) -> FrozenList[str]:
    return FrozenList(
        folder_glob(other.folder)
        for other in packages
        if other != package
        and (
            not package.folder or other.folder.startswith(f"{package.folder}/")
        )
    )


def names_in(packages: Sequence[Package], layer: Layer) -> FrozenList[str]:
    return FrozenList(
        package.name
        for package in packages
        if package.layer == layer and package.name
    )


def layer_rule(package: Package, packages: Sequence[Package]) -> object:
    if package.layer == Layer.CORE:
        return core_rule(names_in(packages, Layer.CORE), ())
    other, message = APART[package.layer]
    group = tuple(
        glob
        for name in names_in(packages, other)
        for glob in (name, f"{name}/**")
    )
    paths = (
        [
            {
                "name": "react",
                "importNames": list(EFFECT_HOOKS),
                "message": IN_ATOMS,
            }
        ]
        if package.layer == Layer.UI
        else []
    )
    patterns = (
        [{"group": list(group), "caseSensitive": True, "message": message}]
        if group
        else []
    )
    rule = {
        key: value
        for key, value in (("paths", paths), ("patterns", patterns))
        if value
    }
    return rule or None


def allowances(
    placed: Sequence[Placement], exceptions: Exceptions
) -> FrozenOrderedDict[FrozenList[str], FrozenList[str]]:
    """The core files of each set of modules that exceptions allow them."""
    grouped: FrozenOrderedDict[FrozenList[str], FrozenList[str]] = (
        FrozenOrderedDict()
    )
    for placement in placed:
        if placement.package.layer != Layer.CORE:
            continue
        allowed = FrozenList(
            found[1]
            for entry in exceptions.entries
            if (found := TYPESCRIPT_PURITY.fullmatch(entry.rule))
            and matches(placement.file, entry.path)
        )
        if allowed:
            files = grouped.get(allowed, FrozenList())
            grouped |= {allowed: FrozenList((*files, placement.file))}
    return grouped


def import_overrides(
    root: str, placed: Sequence[Placement], exceptions: Exceptions
) -> str:
    """An override per package restricting its imports to its layer's, one
    per UI package with its bans beyond imports, then one per set of modules
    that purity exceptions allow core files."""
    packages = packages_of(placed)
    core = names_in(packages, Layer.CORE)
    layers = "".join(
        scoped(
            root,
            (folder_glob(package.folder),),
            nested_in(package, packages),
            imports(rule),
        )
        for package in packages
        if (rule := layer_rule(package, packages)) is not None
    )
    bans = "".join(
        scoped(
            root,
            (folder_glob(package.folder),),
            nested_in(package, packages),
            ui_bans(),
        )
        for package in packages
        if package.layer == Layer.UI
    )
    excepted = "".join(
        scoped(root, files, (), imports(core_rule(core, allowed)))
        for allowed, files in allowances(placed, exceptions).items()
    )
    return layers + bans + excepted
