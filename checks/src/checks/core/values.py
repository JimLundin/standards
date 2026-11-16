import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import cast

from ordered import FrozenList, FrozenOrderedDict

EMPTY: FrozenOrderedDict[str, object] = FrozenOrderedDict()
DRIVE = re.compile(r"[A-Za-z]:/")


@dataclass(frozen=True, slots=True)
class Inputs:
    texts: FrozenOrderedDict[str, str] = field(
        default_factory=FrozenOrderedDict
    )
    stdin: str = ""
    cwd: str = ""


@dataclass(frozen=True, slots=True)
class Request:
    paths: FrozenList[str] = field(default_factory=FrozenList)
    stdin: bool = False


@dataclass(frozen=True, slots=True)
class Outcome:
    lines: FrozenList[str] = field(default_factory=FrozenList)
    status: int = 0
    writes: FrozenOrderedDict[str, str] = field(
        default_factory=FrozenOrderedDict
    )


def table(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)
    return EMPTY


def entries(value: object) -> FrozenList[object]:
    if isinstance(value, list):
        return FrozenList(cast("Sequence[object]", value))
    return FrozenList()


def strings(value: object) -> FrozenList[str]:
    return FrozenList(item for item in entries(value) if isinstance(item, str))


def lookup(data: Mapping[str, object], dotted: str) -> object:
    value: object = data
    for key in dotted.split("."):
        value = table(value).get(key)
    return value


def parse_toml(text: str | None) -> Mapping[str, object]:
    if text is None:
        return EMPTY
    return cast("Mapping[str, object]", tomllib.loads(text))


def parse_json(text: str | None) -> Mapping[str, object]:
    if text is None:
        return EMPTY
    try:
        return table(cast("object", json.loads(text)))
    except json.JSONDecodeError:
        return EMPTY


def matches(path: str, glob: str) -> bool:
    return PurePosixPath(path).full_match(glob)


def posix(path: str) -> str:
    return path.replace("\\", "/")


def normalized(path: str) -> str:
    parts: FrozenList[str] = FrozenList()
    for part in posix(path).split("/"):
        if part == ".." and parts and parts[-1] not in {"", ".."}:
            parts = parts[:-1]
        elif part != "." and (part or not parts):
            parts += (part,)
    return "/".join(parts)


def absolute(path: str, cwd: str) -> str:
    path = posix(path)
    if path.startswith("/") or DRIVE.match(path):
        return path
    return f"{posix(cwd)}/{path}"


def summarized(lines: Sequence[str]) -> Outcome:
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    return Outcome(FrozenList((*lines, summary)), 1 if lines else 0)


def options(arguments: Sequence[str], prefix: str) -> FrozenList[str]:
    return FrozenList(
        argument.removeprefix(prefix)
        for argument in arguments
        if argument.startswith(prefix)
    )


def operands(arguments: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        argument for argument in arguments if not argument.startswith("--")
    )
