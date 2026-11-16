import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

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
    shell: bool


def table(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return cast("Mapping[str, object]", value)
    return MappingProxyType({})


def entries(value: object) -> tuple[object, ...]:
    if isinstance(value, list):
        return tuple(cast("Iterable[object]", value))
    return ()


def function(line: str) -> Function | None:
    record = table(cast("object", json.loads(line)))
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


def functions(lines: Iterable[str]) -> tuple[Function, ...]:
    found = (function(line) for line in lines if line.startswith("{"))
    return tuple(dict.fromkeys(item for item in found if item is not None))


def decisions(items: Iterable[Function]) -> int:
    return sum(item.score - 1 for item in items)


def findings(
    items: tuple[Function, ...], skips: tuple[str, ...]
) -> tuple[str, ...]:
    complex_functions = tuple(
        f"{item.path}:{item.line}: {COMPLEX} {item.score} (limit {LIMIT}){MOVE}"
        for item in items
        if item.shell
        and item.score > LIMIT
        and not any(PurePosixPath(item.path).full_match(glob) for glob in skips)
    )
    total = decisions(items)
    shell = decisions(item for item in items if item.shell)
    share = (
        (
            f"Cargo.toml: {SHARED} {shell} of {total} decisions (limit {SHARE:.0%}){MOVE}",
        )
        if total >= FLOOR
        and shell > SHARE * total
        and not any(
            PurePosixPath("Cargo.toml").full_match(glob) for glob in skips
        )
        else ()
    )
    return (*complex_functions, *share)


def shell_files(items: tuple[Function, ...]) -> tuple[str, ...]:
    core = frozenset(item.path for item in items if not item.shell)
    return tuple(
        dict.fromkeys(
            item.path for item in items if item.shell and item.path not in core
        )
    )


def summary(items: tuple[Function, ...], issues: tuple[str, ...]) -> str:
    if issues:
        return f"Found {len(issues)} issues"
    if not any(item.shell for item in items):
        return "no binaries"
    shell = decisions(item for item in items if item.shell)
    return f"shell makes {shell} of {decisions(items)} decisions"


def main() -> int:
    arguments = tuple(sys.argv[1:])
    skips = tuple(
        argument.removeprefix("--skip=")
        for argument in arguments
        if argument.startswith("--skip=")
    )
    messages, files = (
        Path(argument)
        for argument in arguments
        if not argument.startswith("--")
    )
    items = functions(messages.read_text(encoding="utf-8").splitlines())
    issues = findings(items, skips)
    _ = files.write_text(
        "".join(f"{path}\n" for path in shell_files(items)), encoding="utf-8"
    )
    output = "".join(f"{line}\n" for line in (*issues, summary(items, issues)))
    _ = sys.stdout.write(output)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
