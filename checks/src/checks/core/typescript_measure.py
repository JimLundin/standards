from dataclasses import dataclass
lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.typescript_layers import Layer, named_layer
from checks.core.values import parse_json


@dataclass(frozen=True, slots=True)
class Function:
    """A function and the decisions it makes."""

    layer: Layer
    root: str
    path: str
    line: int
    name: str
    decisions: int


@dataclass(frozen=True, slots=True)
class Entry:
    """A call that starts a runtime, such as `runMain` or `createRoot`."""

    layer: Layer
    root: str
    path: str
    line: int
    call: str


@dataclass(frozen=True, slots=True)
class Reached:
    """A thing a core export reaches that isn't data."""

    layer: Layer
    root: str
    path: str
    line: int
    export: str
    api: str


@dataclass(frozen=True, slots=True)
class Failure:
    """A file typescript-measure couldn't read."""

    layer: Layer
    root: str
    path: str
    error: str


type Record = Function | Entry | Reached | Failure


# typescript-measure tells its records apart by the key each kind alone has.
def decoded(line: str) -> Record | None:
    data = parse_json(line)
    layer = named_layer(data.get("layer"))
    if layer is None:
        return None
    match data:
        case {
            "entry": str(call),
            "root": str(root),
            "path": str(path),
            "line": int(number),
        }:
            return Entry(layer, root, path, number, call)
        case {
            "api": str(api),
            "export": str(export),
            "root": str(root),
            "path": str(path),
            "line": int(number),
        }:
            return Reached(layer, root, path, number, export, api)
        case {"error": str(error), "root": str(root), "path": str(path)}:
            return Failure(layer, root, path, error)
        case {
            "function": str(name),
            "decisions": int(decisions),
            "root": str(root),
            "path": str(path),
            "line": int(number),
        }:
            return Function(layer, root, path, number, name, decisions)
        case _:
            return None


def records(text: str) -> FrozenList[Record]:
    return FrozenList(
        dict.fromkeys(
            found
            for line in text.splitlines()
            if (found := decoded(line)) is not None
        )
    )


def entries(items: Sequence[Record]) -> FrozenList[Entry]:
    return FrozenList(item for item in items if isinstance(item, Entry))
