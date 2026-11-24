import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.decoding import decode
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    absolute,
    entries,
    is_table,
    listing,
    lookup,
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


def layer_overrides(
    placed: Sequence[Placement], rules: Mapping[str, object]
) -> list[object]:
    packages = packages_of(placed)
    return [
        {
            **table(rules[str(layer)]),
            "includes": [
                *scope(package, FrozenList(packages)),
                *strings(table(rules[str(layer)]).get("includes")),
            ],
        }
        for package, layer in packages.items()
        if str(layer) in rules
    ]


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
    folder = str(PurePosixPath(absolute(base, inputs.cwd)).parent)
    moved = {
        key: move(config[key], folder)
        for key, move in (("plugins", plugins_from), ("extends", extends_from))
        if key in config
    }
    overrides = [
        *entries(config.get("overrides")),
        *layer_overrides(placed, parse_json(inputs.texts.get(rules))),
    ]
    generated = {**config, **moved, "overrides": overrides}
    return Outcome(
        writes=FrozenOrderedDict({
            out: f"{json.dumps(generated, indent='\t')}\n"
        })
    )
