import json
lazy from collections.abc import Mapping

from checks.core.typescript_layers import Layer
from checks.core.typescript_measure import (
    Entry,
    Failure,
    Function,
    Reached,
    records,
)

CORE = "packages/core"


def compact(record: Mapping[str, object]) -> str:
    return json.dumps(record, separators=(",", ":"))


def test_each_kind_of_record_is_read_once_into_its_type() -> None:
    function = compact({
        "decisions": 3,
        "function": "View",
        "layer": "ui",
        "line": 2,
        "path": "packages/ui/src/view.tsx",
        "root": "packages/ui",
    })
    text = "\n".join((
        compact({
            "entry": "runMain",
            "layer": "shell",
            "line": 5,
            "path": "packages/shell/main.ts",
            "root": "packages/shell",
        }),
        function,
        compact({
            "api": "reaches `Promise`",
            "export": "promised",
            "layer": "core",
            "line": 3,
            "path": f"{CORE}/src/a.ts",
            "root": CORE,
        }),
        compact({
            "error": "not in the project",
            "layer": "core",
            "path": f"{CORE}/src/gone.ts",
            "root": CORE,
        }),
        function,
    ))
    assert records(text) == (
        Entry(
            Layer.SHELL,
            "packages/shell",
            "packages/shell/main.ts",
            5,
            "runMain",
        ),
        Function(
            Layer.UI, "packages/ui", "packages/ui/src/view.tsx", 2, "View", 3
        ),
        Reached(
            Layer.CORE,
            CORE,
            f"{CORE}/src/a.ts",
            3,
            "promised",
            "reaches `Promise`",
        ),
        Failure(Layer.CORE, CORE, f"{CORE}/src/gone.ts", "not in the project"),
    )


def test_lines_that_arent_records_are_skipped() -> None:
    text = "\n".join((
        "warning: something",
        compact({"function": "f", "decisions": "2", "layer": "core"}),
        compact({
            "decisions": 2,
            "function": "f",
            "layer": "Core",
            "line": 1,
            "path": f"{CORE}/src/a.ts",
            "root": CORE,
        }),
        "",
    ))
    assert records(text) == ()
