import re
from dataclasses import dataclass
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    matches,
    operands,
    options,
    parse_json,
    table,
)

LIMIT = 3
SHARE = 0.25
FLOOR = 20
LINT = "clippy::cognitive_complexity"
COMPLEX = "a shell function has cognitive complexity"
SHARED = "the shell makes"
MOVE = "; move the decisions into the core"
SCORE = re.compile(r"complexity of \((\d+)/")


@dataclass(frozen=True, slots=True)
class Function:
    path: str
    line: int
    score: int
    binary: bool


def function(line: str) -> Function | None:
    record = parse_json(line)
    message = table(record.get("message"))
    if table(message.get("code")).get("code") != LINT:
        return None
    score = SCORE.search(str(message.get("message")))
    spans = tuple(
        table(span)
        for span in entries(message.get("spans"))
        if table(span).get("is_primary")
    )
    if score is None or not spans:
        return None
    kinds = entries(table(record.get("target")).get("kind"))
    return Function(
        str(spans[0].get("file_name")),
        int(str(spans[0].get("line_start"))),
        int(score[1]),
        "bin" in kinds,
    )


def functions(lines: Sequence[str]) -> FrozenList[Function]:
    found = (function(line) for line in lines if line.startswith("{"))
    return FrozenList(dict.fromkeys(item for item in found if item is not None))


def shell_functions(items: Sequence[Function]) -> FrozenList[Function]:
    return FrozenList(item for item in items if item.binary)


def decisions(items: Sequence[Function]) -> int:
    return sum(item.score - 1 for item in items)


def findings(
    items: Sequence[Function], skips: Sequence[str]
) -> FrozenList[str]:
    complex_functions = FrozenList(
        f"{item.path}:{item.line}: {COMPLEX} {item.score} (limit {LIMIT}){MOVE}"
        for item in items
        if item.binary
        and item.score > LIMIT
        and not any(matches(item.path, glob) for glob in skips)
    )
    total = decisions(items)
    shell = decisions(shell_functions(items))
    share = (
        (
            f"Cargo.toml: {SHARED} {shell} of {total} decisions (limit {SHARE:.0%}){MOVE}",
        )
        if total >= FLOOR
        and shell > SHARE * total
        and not any(matches("Cargo.toml", glob) for glob in skips)
        else ()
    )
    return complex_functions + share


def shell_files(items: Sequence[Function]) -> FrozenList[str]:
    core = FrozenOrderedSet(item.path for item in items if not item.binary)
    return FrozenList(
        dict.fromkeys(
            item.path for item in items if item.binary and item.path not in core
        )
    )


def summary(items: Sequence[Function], issues: Sequence[str]) -> str:
    if issues:
        return f"Found {len(issues)} issues"
    if not any(item.binary for item in items):
        return "no binaries"
    shell = decisions(shell_functions(items))
    return f"shell makes {shell} of {decisions(items)} decisions"


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(operands(arguments)[:1])


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    messages, files = operands(arguments)
    items = functions(FrozenList(inputs.texts[messages].splitlines()))
    issues = findings(items, options(arguments, "--skip="))
    return Outcome(
        FrozenList((*issues, summary(items, issues))),
        1 if issues else 0,
        FrozenOrderedDict({
            files: "".join(f"{path}\n" for path in shell_files(items))
        }),
    )
