import json

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import inputs

SHELL = "packages/shell"
UI = "packages/ui"


def entry(call: str, layer: str, root: str, path: str, line: int) -> str:
    return json.dumps(
        {
            "entry": call,
            "layer": layer,
            "line": line,
            "path": path,
            "root": root,
        },
        sort_keys=True,
    )


def run_main(path: str, line: int) -> str:
    return entry("runMain", "shell", SHELL, path, line)


def create_root(root: str, path: str, line: int) -> str:
    return entry("createRoot", "ui", root, path, line)


FUNCTION = json.dumps({
    "decisions": 1,
    "function": "main",
    "layer": "shell",
    "line": 1,
    "path": f"{SHELL}/main.ts",
    "root": SHELL,
})


def entered(*lines: str) -> Outcome:
    return run(
        ("typescript-entry", "m.jsonl"), inputs({"m.jsonl": "\n".join(lines)})
    )


def test_entry_reads_the_exceptions_and_the_records() -> None:
    assert request(("typescript-entry", "m.jsonl"), Inputs()) == Request(
        FrozenList(("exceptions.toml", "m.jsonl"))
    )


def test_one_run_main_and_one_create_root_per_ui_package_pass() -> None:
    assert entered(
        FUNCTION,
        run_main(f"{SHELL}/main.ts", 5),
        create_root(UI, f"{UI}/src/main.tsx", 4),
        create_root("packages/admin", "packages/admin/src/main.tsx", 4),
    ) == Outcome(FrozenList(("1 runMain, 2 createRoot",)), 0)


def test_a_second_run_main_in_the_project_fails() -> None:
    assert entered(
        run_main(f"{SHELL}/main.ts", 5),
        entry(
            "runMain", "core", "packages/core", "packages/core/src/run.ts", 3
        ),
    ) == Outcome(
        FrozenList((
            f"{SHELL}/main.ts:5: the project calls NodeRuntime.runMain 2 times (limit 1)",
            "packages/core/src/run.ts:3: the project calls NodeRuntime.runMain 2 times (limit 1)",
            "Found 2 issues",
        )),
        1,
    )


def test_a_second_create_root_in_a_ui_package_fails() -> None:
    assert entered(
        create_root(UI, f"{UI}/src/main.tsx", 4),
        create_root("packages/admin", "packages/admin/src/main.tsx", 4),
        create_root(UI, f"{UI}/src/other.tsx", 7),
    ) == Outcome(
        FrozenList((
            f"{UI}/src/main.tsx:4: {UI} calls createRoot 2 times (limit 1)",
            f"{UI}/src/other.tsx:7: {UI} calls createRoot 2 times (limit 1)",
            "Found 2 issues",
        )),
        1,
    )


def test_a_create_root_outside_a_ui_package_is_not_counted() -> None:
    assert entered(
        create_root(UI, f"{UI}/src/main.tsx", 4),
        entry("createRoot", "shell", SHELL, f"{SHELL}/src/page.tsx", 2),
    ) == Outcome(FrozenList(("0 runMain, 1 createRoot",)), 0)
