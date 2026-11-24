from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList

from checks.core.exceptions import API, EXCEPTIONS, exceptions_in
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    parse_json,
    summarized,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CORE = "core"
ONLY_DATA = "; the core's API takes only data"


@dataclass(frozen=True, slots=True)
class Reached:
    """A thing a core export reaches that isn't data, from an api record."""

    path: str
    line: int
    name: str
    api: str

    def finding(self) -> str:
        return f"{self.path}:{self.line}: `{self.name}` {self.api}{ONLY_DATA}"


@dataclass(frozen=True, slots=True)
class Unread:
    """A core file typescript-measure couldn't read."""

    path: str
    error: str

    def finding(self) -> str:
        return f"{self.path}: cannot be judged: {self.error}"


def judged(record: Mapping[str, object]) -> Reached | Unread | None:
    path = str(record.get("path"))
    if record.get("layer") != CORE:
        return None
    if "api" in record:
        return Reached(
            path,
            int(str(record.get("line"))),
            str(record.get("export")),
            str(record.get("api")),
        )
    if "error" in record:
        return Unread(path, str(record.get("error")))
    return None


def found(lines: Sequence[str]) -> FrozenList[Reached | Unread]:
    return FrozenList(
        item
        for line in lines
        if line.startswith("{")
        and (item := judged(parse_json(line))) is not None
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, arguments[0])))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    items = found(text(inputs.texts, arguments[0]).splitlines())
    return summarized(
        FrozenList(
            item.finding()
            for item in sorted(
                items,
                key=lambda item: (
                    item.path,
                    item.line if isinstance(item, Reached) else 0,
                ),
            )
            if not exceptions.covers(API, item.path)
        )
    )
