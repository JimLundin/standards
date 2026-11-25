from dataclasses import dataclass, replace
from enum import StrEnum
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core import typescript_measure
from checks.core.cargo import is_shell, kinds, packages_of, relative, targets_of
from checks.core.exceptions import EXCEPTIONS, SHELL, Exceptions, exceptions_in
from checks.core.typescript_layers import OUTER_LAYERS, Layer
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
CARGO = "Cargo.toml"
PACKAGE = "package.json"
SHARED = "the shell makes"
MOVE = "; move the decisions into the core"
UNMEASURED = "cannot be measured"


class Role(StrEnum):
    SHELL_FUNCTION = "the shell function"
    COMPONENT = "the component"


@dataclass(frozen=True, slots=True)
class Function:
    path: str
    line: int
    name: str
    decisions: int
    in_shell: bool
    role: Role


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
    return Function(
        path,
        int(str(record.get("line"))),
        str(record.get("function")),
        int(str(record.get("decisions"))),
        roots.get(str(record.get("root")), False),
        Role.SHELL_FUNCTION,
    )


def records(
    lines: Sequence[str], metadata: Mapping[str, object]
) -> FrozenList[Function | Failure]:
    roots, root = targets(metadata), str(metadata.get("workspace_root"))
    return FrozenList(
        dict.fromkeys(
            measured(line, roots, root)
            for line in lines
            if line.startswith("{")
        )
    )


def typescript_item(
    record: typescript_measure.Function | typescript_measure.Failure,
) -> Function | Failure:
    match record:
        case typescript_measure.Function():
            return Function(
                record.path,
                record.line,
                record.name,
                record.decisions,
                record.layer in OUTER_LAYERS,
                Role.COMPONENT
                if record.layer == Layer.UI
                else Role.SHELL_FUNCTION,
            )
        case typescript_measure.Failure():
            return Failure(record.path, record.error)


def typescript_records(text: str) -> FrozenList[Function | Failure]:
    return FrozenList(
        typescript_item(record)
        for record in typescript_measure.records(text)
        if isinstance(
            record, (typescript_measure.Function, typescript_measure.Failure)
        )
    )


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
        f"{item.path}:{item.line}: {item.role} `{item.name}` makes {item.decisions} decisions (limit {LIMIT}){MOVE}"
        for item in shell_functions(functions(items))
        if item.decisions > LIMIT and not exceptions.covers(SHELL, item.path)
    )
    return unmeasured + complex_functions


def share_findings(
    items: Sequence[Function], exceptions: Exceptions, manifest: str
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


def verdict(items: Sequence[Function | Failure], inputs: Inputs) -> Outcome:
    return summarized(
        findings(items, exceptions_in(inputs)), passing(functions(items))
    )


def share_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return shared_verdict(measures_of(arguments, inputs), inputs, CARGO)


# Rust's mutation step skips the shell's files, which the shell unit writes
# to the file the third argument names.
def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    items = measures_of(arguments, inputs)
    return replace(
        verdict(items, inputs),
        writes=FrozenOrderedDict({
            arguments[2]: "".join(
                f"{path}\n" for path in shell_files(functions(items))
            )
        }),
    )


def typescript_measures(
    arguments: Sequence[str], inputs: Inputs
) -> FrozenList[Function | Failure]:
    return typescript_records(text(inputs.texts, arguments[0]))


def typescript_share_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return shared_verdict(
        typescript_measures(arguments, inputs), inputs, PACKAGE
    )


def typescript_run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return verdict(typescript_measures(arguments, inputs), inputs)
