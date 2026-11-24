import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.decoding import decode
from checks.core.drift import plugin_paths
from checks.core.exceptions import EXCEPTIONS, exceptions_in
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    absolute,
    entries,
    is_table,
    listing,
    lookup,
    matches,
    normalized,
    operands,
    parse_json,
    strings,
    table,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LAYERS = FrozenOrderedSet(("core", "shell", "ui"))
UNDECLARED = "core"
LAYER = "standards.layer"
USE = 'use "core", "shell" or "ui"'


@dataclass(frozen=True, slots=True)
class Placement:
    """A file in its nearest package, whose folder is "" at the root."""

    file: str
    package: str
    layer: object


def folders(file: str) -> FrozenList[str]:
    parts = file.split("/")[:-1]
    return FrozenList(
        "/".join(parts[:end]) for end in range(len(parts), -1, -1)
    )


def manifest(folder: str) -> str:
    return f"{folder}/package.json" if folder else "package.json"


def manifests(files: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        FrozenOrderedSet(
            manifest(folder) for file in files for folder in folders(file)
        )
    )


def declared(texts: Mapping[str, str], package: str) -> object:
    layer = lookup(parse_json(texts.get(manifest(package))), LAYER)
    return UNDECLARED if layer is None else layer


def placements(
    files: Sequence[str], texts: Mapping[str, str]
) -> FrozenList[Placement]:
    packages = FrozenList(
        next(
            (folder for folder in folders(file) if manifest(folder) in texts),
            "",
        )
        for file in files
    )
    return FrozenList(
        Placement(file, package, declared(texts, package))
        for file, package in zip(files, packages, strict=True)
    )


def packages_of(placed: Sequence[Placement]) -> FrozenOrderedDict[str, object]:
    return FrozenOrderedDict(
        (placement.package, placement.layer) for placement in placed
    )


def layer_issues(placed: Sequence[Placement]) -> FrozenList[str]:
    return FrozenList(
        f"{manifest(package)}: {LAYER} is {json.dumps(layer)}; {USE}"
        for package, layer in packages_of(placed).items()
        if not (isinstance(layer, str) and layer in LAYERS)
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(manifests(operands(arguments)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    placed = placements(operands(arguments), inputs.texts)
    if issues := layer_issues(placed):
        return Outcome(issues, 1)
    return listing(
        FrozenList(
            f"{placement.layer}\t{placement.package or '.'}\t{placement.file}"
            for placement in placed
        )
    )


def json_object(text: str | None) -> Mapping[str, object] | None:
    if text is None:
        return None
    try:
        loaded = decode(text)
    except json.JSONDecodeError:
        return None
    return loaded if is_table(loaded) else None


def relocated(path: str, folder: str) -> str:
    return normalized(absolute(path, folder))


def plugins_from(plugins: object, folder: str) -> list[object]:
    return [
        relocated(plugin, folder)
        if isinstance(plugin, str)
        else {
            **table(plugin),
            "path": relocated(str(table(plugin).get("path", "")), folder),
        }
        for plugin in entries(plugins)
    ]


def extends_from(extends: object, folder: str) -> list[str]:
    return [
        relocated(path, folder) if path.startswith(".") else path
        for path in strings(extends)
    ]


def scope(package: str, packages: Sequence[str]) -> FrozenList[str]:
    """Globs of a package's folder without the packages nested in it."""
    nested = FrozenList(
        other
        for other in packages
        if other != package and (not package or other.startswith(f"{package}/"))
    )
    return FrozenList((
        f"{package}/**" if package else "**",
        *(f"!{other}/**" for other in nested),
    ))


def with_plugins_from(settings: Mapping[str, object], folder: str) -> object:
    if "plugins" not in settings:
        return settings
    return {**settings, "plugins": plugins_from(settings["plugins"], folder)}


def layer_overrides(
    placed: Sequence[Placement], rules: Mapping[str, object], folder: str
) -> list[object]:
    packages = packages_of(placed)
    return [
        {
            **table(with_plugins_from(table(rules[str(layer)]), folder)),
            "includes": [
                *scope(package, FrozenList(packages)),
                *strings(table(rules[str(layer)]).get("includes")),
            ],
        }
        for package, layer in packages.items()
        if str(layer) in rules
    ]


def folder_of(config: str, cwd: str) -> str:
    return str(PurePosixPath(absolute(config, cwd)).parent)


def included(file: str, includes: Sequence[str]) -> bool:
    """Whether a layer's own includes, Biome globs where `!` excludes,
    keep a file of that layer."""
    wanted = FrozenList(glob for glob in includes if not glob.startswith("!"))
    unwanted = FrozenList(glob[1:] for glob in includes if glob.startswith("!"))
    return (not wanted or any(matches(file, glob) for glob in wanted)) and not (
        any(matches(file, glob) for glob in unwanted)
    )


def layer_files(
    placed: Sequence[Placement], layer: str, settings: Mapping[str, object]
) -> FrozenOrderedSet[str]:
    includes = strings(settings.get("includes"))
    return FrozenOrderedSet(
        placement.file
        for placement in placed
        if placement.layer == layer and included(placement.file, includes)
    )


def named_plugins(
    config: Mapping[str, object], folder: str
) -> FrozenList[tuple[str, str]]:
    return FrozenList(
        (PurePosixPath(path).stem, relocated(path, folder))
        for path in plugin_paths(config)
    )


def plugins_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    base, rules, *files = arguments
    return Request(FrozenList((EXCEPTIONS, base, rules, *manifests(files))))


def plugins_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    """Each plugin of the config, which covers every file, and of the layer
    rules, which cover their layer's files, with the files it lints: a
    `name|path|file...` line per plugin that lints any."""
    base, rules, *files = arguments
    placed = placements(files, inputs.texts)
    if issues := layer_issues(placed):
        return Outcome(issues, 1)
    config = parse_json(inputs.texts.get(base))
    covered: FrozenOrderedDict[tuple[str, str], FrozenOrderedSet[str]] = (
        FrozenOrderedDict(
            (plugin, FrozenOrderedSet(files))
            for plugin in named_plugins(config, folder_of(base, inputs.cwd))
        )
    )
    folder = folder_of(rules, inputs.cwd)
    for layer, settings in parse_json(inputs.texts.get(rules)).items():
        members = layer_files(placed, layer, table(settings))
        for plugin in named_plugins(table(settings), folder):
            covered |= {
                plugin: covered.get(plugin, FrozenOrderedSet()) | members
            }
    exceptions = exceptions_in(inputs)
    return listing(
        FrozenList(
            "|".join((name, path, *kept))
            for (name, path), members in covered.items()
            if (
                kept := FrozenList(
                    file
                    for file in files
                    if file in members
                    and not exceptions.covers(f"lint/plugin/{name}", file)
                )
            )
        )
    )


def config_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    base, rules, _out, *files = arguments
    return Request(FrozenList((base, rules, *manifests(files))))


def config_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    base, rules, out, *files = arguments
    config = json_object(inputs.texts.get(base))
    if config is None:
        return Outcome(FrozenList((f"{base}: not a JSON object",)), 1)
    placed = placements(files, inputs.texts)
    if issues := layer_issues(placed):
        return Outcome(issues, 1)
    folder = folder_of(base, inputs.cwd)
    moved = {
        key: move(config[key], folder)
        for key, move in (("plugins", plugins_from), ("extends", extends_from))
        if key in config
    }
    overrides = [
        *entries(config.get("overrides")),
        *layer_overrides(
            placed,
            parse_json(inputs.texts.get(rules)),
            folder_of(rules, inputs.cwd),
        ),
    ]
    generated = {**config, **moved, "overrides": overrides}
    return Outcome(
        writes=FrozenOrderedDict({
            out: f"{json.dumps(generated, indent='\t')}\n"
        })
    )
