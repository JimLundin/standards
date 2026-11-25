import json

from ordered import FrozenList

from checks.core.tools import request
from checks.core.typescript_api import run
from checks.core.values import Request
from tests.helpers import entry, inputs

RECORDS = "measure.jsonl"
ONLY_DATA = "; the core's API takes only data"


def reached(path: str, line: int, name: str, api: str) -> str:
    return json.dumps({
        "api": api,
        "export": name,
        "layer": "core",
        "line": line,
        "path": path,
        "root": "packages/core",
    })


def counted(path: str) -> str:
    return json.dumps({
        "decisions": 1,
        "function": "f",
        "layer": "core",
        "line": 1,
        "path": path,
        "root": "packages/core",
    })


def unread(path: str, layer: str) -> str:
    return json.dumps({
        "error": "not in the project",
        "layer": layer,
        "path": path,
        "root": "packages/core",
    })


def test_it_reads_the_exceptions_and_the_records() -> None:
    assert request(("typescript-api", RECORDS), inputs({})) == Request(
        FrozenList(("exceptions.toml", RECORDS))
    )


def test_each_thing_a_core_export_reaches_that_isnt_data_is_a_finding() -> None:
    records = "\n".join((
        reached("packages/core/src/b.ts", 3, "promised", "reaches `Promise`"),
        counted("packages/core/src/b.ts"),
        reached(
            "packages/core/src/a.ts",
            2,
            "Runner",
            "is a class with methods, `run`",
        ),
    ))
    outcome = run([RECORDS], inputs({RECORDS: records}))
    assert outcome.lines == FrozenList((
        f"packages/core/src/a.ts:2: `Runner` is a class with methods, `run`{ONLY_DATA}",
        f"packages/core/src/b.ts:3: `promised` reaches `Promise`{ONLY_DATA}",
        "Found 2 issues",
    ))
    assert outcome.status == 1


def test_an_api_exception_clears_its_files_findings() -> None:
    records = "\n".join((
        reached("packages/core/src/a.ts", 2, "f", "reaches `Promise`"),
        reached("packages/core/src/b.ts", 2, "g", "reaches `Promise`"),
    ))
    texts = {
        RECORDS: records,
        "exceptions.toml": entry("packages/core/src/a.ts", "api"),
    }
    assert run([RECORDS], inputs(texts)).lines == FrozenList((
        f"packages/core/src/b.ts:2: `g` reaches `Promise`{ONLY_DATA}",
        "Found 1 issues",
    ))


def test_a_core_file_that_cant_be_read_fails_and_another_layers_doesnt() -> (
    None
):
    records = "\n".join((
        unread("packages/core/src/gone.ts", "core"),
        unread("packages/shell/src/gone.ts", "shell"),
    ))
    assert run([RECORDS], inputs({RECORDS: records})).lines == FrozenList((
        "packages/core/src/gone.ts: cannot be judged: not in the project",
        "Found 1 issues",
    ))


def test_a_files_findings_list_its_unread_failure_then_its_lines_in_order() -> (
    None
):
    path = "packages/core/src/a.ts"
    records = "\n".join((
        reached(path, 3, "late", "reaches `Promise`"),
        reached(path, 1, "early", "reaches `Promise`"),
        unread(path, "core"),
    ))
    assert run([RECORDS], inputs({RECORDS: records})).lines == FrozenList((
        f"{path}: cannot be judged: not in the project",
        f"{path}:1: `early` reaches `Promise`{ONLY_DATA}",
        f"{path}:3: `late` reaches `Promise`{ONLY_DATA}",
        "Found 3 issues",
    ))
