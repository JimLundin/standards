from typing import TYPE_CHECKING

from ordered import FrozenList

from checks.core.exceptions import API, exceptions_in
from checks.core.typescript_layers import Layer
from checks.core.typescript_measure import Failure, Reached, records
from checks.core.values import Inputs, Outcome, summarized, text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from checks.core.typescript_measure import Record

ONLY_DATA = "; the core's API takes only data"


def finding(item: Reached | Failure) -> str:
    match item:
        case Reached():
            return f"{item.path}:{item.line}: `{item.export}` {item.api}{ONLY_DATA}"
        case Failure():
            return f"{item.path}: cannot be judged: {item.error}"


def judged(items: Sequence[Record]) -> FrozenList[Reached | Failure]:
    return FrozenList(
        item
        for item in items
        if isinstance(item, (Reached, Failure)) and item.layer == Layer.CORE
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    items = judged(records(text(inputs.texts, arguments[0])))
    return summarized(
        FrozenList(
            finding(item)
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
