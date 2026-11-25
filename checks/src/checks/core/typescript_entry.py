lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.typescript_measure import Entry, entries, records
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    operands,
    summarized,
    text,
)

RUN_MAIN = "runMain"
CREATE_ROOT = "createRoot"
UI = "ui"
LIMIT = 1


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
    items = entries(records(text(inputs.texts, operands(arguments)[0])))
    mains = sum(item.call == RUN_MAIN for item in items)
    return summarized(
        findings(items),
        f"{mains} {RUN_MAIN}, {len(mounted(items))} {CREATE_ROOT}",
    )
