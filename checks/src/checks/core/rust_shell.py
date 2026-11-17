from dataclasses import dataclass
from pathlib import PurePosixPath
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import is_shell, listing, packages_of
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    matches,
    normalized,
    operands,
    options,
    parse_json,
    posix,
    strings,
    table,
)

LIMIT = 2
SHARE = 0.25
FLOOR = 20
MEASURED_KINDS = FrozenOrderedSet((
    "bin",
    "lib",
    "rlib",
    "dylib",
    "cdylib",
    "staticlib",
    "proc-macro",
))
COMPLEX = "the shell function"
SHARED = "the shell makes"
MOVE = "; move the decisions into the core"
UNMEASURED = "cannot be measured"


@dataclass(frozen=True, slots=True)
class Function:
    path: str
    line: int
    name: str
    decisions: int
    in_shell: bool


@dataclass(frozen=True, slots=True)
class Failure:
    path: str
    error: str


def kinds(target: Mapping[str, object]) -> FrozenList[str]:
    return strings(target.get("kind"))


def package_targets(
    package: Mapping[str, object],
) -> FrozenList[tuple[str, bool]]:
    return FrozenList(
        (
            str(target.get("src_path")),
            "bin" in kinds(target) or is_shell(package),
        )
        for target in map(table, entries(package.get("targets")))
        if any(kind in MEASURED_KINDS for kind in kinds(target))
    )


def targets(metadata: Mapping[str, object]) -> FrozenOrderedDict[str, bool]:
    return FrozenOrderedDict(
        target
        for package in packages_of(metadata)
        for target in package_targets(package)
    )


def relative(path: str, root: str) -> str:
    whole = PurePosixPath(normalized(path))
    if whole.is_relative_to(posix(root)):
        return whole.relative_to(posix(root)).as_posix()
    return whole.as_posix()


def measured(
    line: str, roots: Mapping[str, bool], root: str
) -> Function | Failure:
    record = parse_json(line)
    path = relative(str(record.get("path")), root)
    if "error" in record:
        return Failure(path, str(record.get("error")))
    return Function(
        path,
        int(str(record.get("line"))),
        str(record.get("function")),
        int(str(record.get("decisions"))),
        roots.get(str(record.get("root")), False),
    )


def records(
    lines: Sequence[str], metadata: Mapping[str, object]
) -> FrozenList[Function | Failure]:
    roots = targets(metadata)
    root = str(metadata.get("workspace_root"))
    found = (
        measured(line, roots, root) for line in lines if line.startswith("{")
    )
    return FrozenList(dict.fromkeys(found))


def functions(items: Sequence[Function | Failure]) -> FrozenList[Function]:
    return FrozenList(item for item in items if isinstance(item, Function))


def failures(items: Sequence[Function | Failure]) -> FrozenList[Failure]:
    return FrozenList(item for item in items if isinstance(item, Failure))


def shell_functions(items: Sequence[Function]) -> FrozenList[Function]:
    return FrozenList(item for item in items if item.in_shell)


def decisions(items: Sequence[Function]) -> int:
    return sum(item.decisions for item in items)


def waived(path: str, skips: Sequence[str]) -> bool:
    return any(matches(path, glob) for glob in skips)


def findings(
    items: Sequence[Function | Failure], skips: Sequence[str]
) -> FrozenList[str]:
    unmeasured = FrozenList(
        f"{item.path}: {UNMEASURED}: {item.error}"
        for item in failures(items)
        if not waived(item.path, skips)
    )
    measured_functions = functions(items)
    complex_functions = FrozenList(
        f"{item.path}:{item.line}: {COMPLEX} `{item.name}` makes {item.decisions} decisions (limit {LIMIT}){MOVE}"
        for item in shell_functions(measured_functions)
        if item.decisions > LIMIT and not waived(item.path, skips)
    )
    total = decisions(measured_functions)
    shell = decisions(shell_functions(measured_functions))
    share = (
        (
            f"Cargo.toml: {SHARED} {shell} of {total} decisions (limit {SHARE:.0%}){MOVE}",
        )
        if total >= FLOOR
        and shell > SHARE * total
        and not waived("Cargo.toml", skips)
        else ()
    )
    return unmeasured + complex_functions + share


def shell_files(items: Sequence[Function]) -> FrozenList[str]:
    core = FrozenOrderedSet(item.path for item in items if not item.in_shell)
    return FrozenList(
        dict.fromkeys(
            item.path
            for item in items
            if item.in_shell and item.path not in core
        )
    )


def summary(items: Sequence[Function], issues: Sequence[str]) -> str:
    if issues:
        return f"Found {len(issues)} issues"
    if not shell_functions(items):
        return "no shell"
    shell = decisions(shell_functions(items))
    return f"shell makes {shell} of {decisions(items)} decisions"


def roots_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(operands(arguments)[:1])


def roots(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata = parse_json(inputs.texts.get(operands(arguments)[0]))
    return listing(FrozenList(targets(metadata)))


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(operands(arguments)[:2])


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata, measures, files = operands(arguments)
    items = records(
        FrozenList(inputs.texts.get(measures, "").splitlines()),
        parse_json(inputs.texts.get(metadata)),
    )
    issues = findings(items, options(arguments, "--skip="))
    measured_functions = functions(items)
    return Outcome(
        FrozenList((*issues, summary(measured_functions, issues))),
        1 if issues else 0,
        FrozenOrderedDict({
            files: "".join(
                f"{path}\n" for path in shell_files(measured_functions)
            )
        }),
    )
