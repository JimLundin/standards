import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TypeIs

from ordered import FrozenList, FrozenOrderedDict

from checks.core.decoding import decode

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


def is_table(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def table(value: object) -> Mapping[str, object]:
    return value if is_table(value) else EMPTY


def entries(value: object) -> FrozenList[object]:
    return FrozenList(value) if is_list(value) else FrozenList()


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
    return tomllib.loads(text)


def parse_json(text: str | None) -> Mapping[str, object]:
    if text is None:
        return EMPTY
    try:
        loaded = decode(text)
    except json.JSONDecodeError:
        return EMPTY
    return table(loaded)


def matches(path: str, glob: str) -> bool:
    return PurePosixPath(path).full_match(glob)


def posix(path: str) -> str:
    return path.replace("\\", "/")


def normalized(path: str) -> str:
    parts: FrozenList[str] = FrozenList()
    for part in posix(path).split("/"):
        if part == "." or (not part and parts):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts = parts if parts == ("",) else parts[:-1]
            continue
        parts = FrozenList((*parts, part))
    return "/".join(parts)


def absolute(path: str, cwd: str) -> str:
    path = posix(path)
    if path.startswith("/") or DRIVE.match(path):
        return path
    return f"{posix(cwd)}/{path}"


def within(module: str, roots: Sequence[str]) -> bool:
    return any(
        module == root or module.startswith(f"{root}.") for root in roots
    )


def summarized(
    lines: Sequence[str], passing: str = "All checks passed"
) -> Outcome:
    summary = f"Found {len(lines)} issues" if lines else passing
    return Outcome(FrozenList((*lines, summary)), 1 if lines else 0)


def listing(lines: Sequence[str]) -> Outcome:
    return Outcome(FrozenList(line for line in lines if line))


def options(arguments: Sequence[str], prefix: str) -> FrozenList[str]:
    return FrozenList(
        argument.removeprefix(prefix)
        for argument in arguments
        if argument.startswith(prefix)
    )


def option(arguments: Sequence[str], prefix: str) -> str:
    return next(iter(options(arguments, prefix)), "")


def text(texts: Mapping[str, str], path: str) -> str:
    return texts.get(path, "")


def operands(arguments: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        argument for argument in arguments if not argument.startswith("--")
    )
