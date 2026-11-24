from dataclasses import dataclass
lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    operands,
    parse_json,
    summarized,
    text,
)

RUN_MAIN = "runMain"
CREATE_ROOT = "createRoot"
UI = "ui"
LIMIT = 1


@dataclass(frozen=True, slots=True)
class Entry:
    """A call of typescript/measure's entry records: a runtime's start."""

    call: str
    layer: str
    root: str
    path: str
    line: int


def entry(line: str) -> Entry | None:
    record = parse_json(line)
    call, layer, root, path, number = (
        record.get(key) for key in ("entry", "layer", "root", "path", "line")
    )
    if not (
        isinstance(call, str)
        and isinstance(layer, str)
        and isinstance(root, str)
        and isinstance(path, str)
        and isinstance(number, int)
    ):
        return None
    return Entry(call, layer, root, path, number)


def entries(lines: Sequence[str]) -> FrozenList[Entry]:
    return FrozenList(
        found
        for line in lines
        if line.startswith("{") and (found := entry(line)) is not None
    )


def beyond(items: Sequence[Entry], scope: str, call: str) -> FrozenList[str]:
    return FrozenList(
        f"{item.path}:{item.line}: {scope} calls {call} {len(items)} times (limit {LIMIT})"
        for item in items
        if len(items) > LIMIT
    )


def mounted(items: Sequence[Entry]) -> FrozenList[Entry]:
    return FrozenList(
        item for item in items if item.call == CREATE_ROOT and item.layer == UI
    )


def findings(items: Sequence[Entry]) -> FrozenList[str]:
    mains = FrozenList(item for item in items if item.call == RUN_MAIN)
    roots = mounted(items)
    return beyond(mains, "the project", "NodeRuntime.runMain") + FrozenList(
        issue
        for root in dict.fromkeys(item.root for item in roots)
        for issue in beyond(
            FrozenList(item for item in roots if item.root == root),
            root,
            CREATE_ROOT,
        )
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(operands(arguments)[:1])


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    items = entries(
        FrozenList(text(inputs.texts, operands(arguments)[0]).splitlines())
    )
    mains = sum(item.call == RUN_MAIN for item in items)
    return summarized(
        findings(items),
        f"{mains} {RUN_MAIN}, {len(mounted(items))} {CREATE_ROOT}",
    )
