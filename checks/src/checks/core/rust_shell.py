from dataclasses import dataclass, replace
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.cargo import is_shell, kinds, packages_of, relative, targets_of
from checks.core.exceptions import EXCEPTIONS, SHELL, Exceptions, exceptions_in
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    listing,
    operands,
    parse_json,
    summarized,
    text,
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
# A TypeScript record's layer, which the UI shares with the shell.
OUTER_LAYERS = FrozenOrderedSet(("shell", "ui"))
CARGO = "Cargo.toml"
PACKAGE = "package.json"
COMPLEX = "the shell function"
SHARED = "the shell makes"
MOVE = "; move the decisions into the core"
UNMEASURED = "cannot be measured"
# typescript-measure's record of an entry point, which the entry unit reads.
ENTRY = "entry"


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


def package_targets(
    package: Mapping[str, object],
) -> FrozenList[tuple[str, bool]]:
    return FrozenList(
        (
            str(target.get("src_path")),
            "bin" in kinds(target) or is_shell(package),
        )
        for target in targets_of(package)
        if any(kind in MEASURED_KINDS for kind in kinds(target))
    )


def targets(metadata: Mapping[str, object]) -> FrozenOrderedDict[str, bool]:
    return FrozenOrderedDict(
        target
        for package in packages_of(metadata)
        for target in package_targets(package)
    )


def measured(
    line: str, roots: Mapping[str, bool], root: str
) -> Function | Failure:
    record = parse_json(line)
    path = relative(str(record.get("path")), root)
    if "error" in record:
        return Failure(path, str(record.get("error")))
    in_shell = (
        record.get("layer") in OUTER_LAYERS
        if "layer" in record
        else roots.get(str(record.get("root")), False)
    )
    return Function(
        path,
        int(str(record.get("line"))),
        str(record.get("function")),
        int(str(record.get("decisions"))),
        in_shell,
    )


def read(
    lines: Sequence[str], roots: Mapping[str, bool], root: str
) -> FrozenList[Function | Failure]:
    found = (
        measured(line, roots, root)
        for line in lines
        if line.startswith("{") and ENTRY not in parse_json(line)
    )
    return FrozenList(dict.fromkeys(found))


def records(
    lines: Sequence[str], metadata: Mapping[str, object]
) -> FrozenList[Function | Failure]:
    return read(lines, targets(metadata), str(metadata.get("workspace_root")))


def typescript_records(lines: Sequence[str]) -> FrozenList[Function | Failure]:
    """typescript-measure's records, whose paths are the project's."""
    return read(lines, FrozenOrderedDict(), "")


def functions(items: Sequence[Function | Failure]) -> FrozenList[Function]:
    return FrozenList(item for item in items if isinstance(item, Function))


def failures(items: Sequence[Function | Failure]) -> FrozenList[Failure]:
    return FrozenList(item for item in items if isinstance(item, Failure))


def shell_functions(items: Sequence[Function]) -> FrozenList[Function]:
    return FrozenList(item for item in items if item.in_shell)


def decisions(items: Sequence[Function]) -> int:
    return sum(item.decisions for item in items)


def findings(
    items: Sequence[Function | Failure], exceptions: Exceptions
) -> FrozenList[str]:
    unmeasured = FrozenList(
        f"{item.path}: {UNMEASURED}: {item.error}"
        for item in failures(items)
        if not exceptions.covers(SHELL, item.path)
    )
    complex_functions = FrozenList(
        f"{item.path}:{item.line}: {COMPLEX} `{item.name}` makes {item.decisions} decisions (limit {LIMIT}){MOVE}"
        for item in shell_functions(functions(items))
        if item.decisions > LIMIT and not exceptions.covers(SHELL, item.path)
    )
    return unmeasured + complex_functions


def share_findings(
    items: Sequence[Function], exceptions: Exceptions, manifest: str = CARGO
) -> FrozenList[str]:
    total = decisions(items)
    shell = decisions(shell_functions(items))
    return FrozenList(
        (
            f"{manifest}: {SHARED} {shell} of {total} decisions (limit {SHARE:.0%}){MOVE}",
        )
        if total >= FLOOR
        and shell > SHARE * total
        and not exceptions.covers(SHELL, manifest)
        else ()
    )


def shell_files(items: Sequence[Function]) -> FrozenList[str]:
    core = FrozenOrderedSet(item.path for item in items if not item.in_shell)
    return FrozenList(
        dict.fromkeys(
            item.path
            for item in items
            if item.in_shell and item.path not in core
        )
    )


def passing(items: Sequence[Function]) -> str:
    if not shell_functions(items):
        return "no shell"
    shell = decisions(shell_functions(items))
    return f"shell makes {shell} of {decisions(items)} decisions"


def roots_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    (metadata,) = operands(arguments)
    return Request(FrozenList((metadata,)))


def roots(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata = parse_json(inputs.texts.get(operands(arguments)[0]))
    return listing(FrozenList(targets(metadata)))


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, *arguments[:2])))


def measures_of(
    arguments: Sequence[str], inputs: Inputs
) -> FrozenList[Function | Failure]:
    metadata, measures, *_ = arguments
    return records(
        FrozenList(text(inputs.texts, measures).splitlines()),
        parse_json(inputs.texts.get(metadata)),
    )


def shared_verdict(
    items: Sequence[Function | Failure], inputs: Inputs, manifest: str
) -> Outcome:
    measured_functions = functions(items)
    return summarized(
        share_findings(measured_functions, exceptions_in(inputs), manifest),
        passing(measured_functions),
    )


def verdict(
    items: Sequence[Function | Failure], inputs: Inputs, files: str
) -> Outcome:
    issues = findings(items, exceptions_in(inputs))
    measured_functions = functions(items)
    return replace(
        summarized(issues, passing(measured_functions)),
        writes=FrozenOrderedDict({
            files: "".join(
                f"{path}\n" for path in shell_files(measured_functions)
            )
        }),
    )


def share_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return shared_verdict(measures_of(arguments, inputs), inputs, CARGO)


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return verdict(measures_of(arguments, inputs), inputs, arguments[2])


def typescript_request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, arguments[0])))


def typescript_measures(
    arguments: Sequence[str], inputs: Inputs
) -> FrozenList[Function | Failure]:
    return typescript_records(
        FrozenList(text(inputs.texts, arguments[0]).splitlines())
    )


def typescript_share_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return shared_verdict(
        typescript_measures(arguments, inputs), inputs, PACKAGE
    )


def typescript_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return verdict(typescript_measures(arguments, inputs), inputs, arguments[1])
