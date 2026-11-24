import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList

from checks.core.exceptions import EXCEPTIONS, Exceptions
from checks.core.values import Inputs, Request, posix

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    advice: str


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class Source:
    module: str
    package: bool = False


def describe(path: str, finding: Finding) -> str:
    location = f"{path}:{finding.line}:{finding.column + 1}"
    code = finding.rule.partition(":")[0]
    return f"{location}: {code} {finding.message}"


def reported(
    path: str, findings: Sequence[Finding], exceptions: Exceptions
) -> Iterator[str]:
    yield from (
        describe(path, finding)
        for finding in sorted(findings, key=lambda f: (f.line, f.column))
        if not exceptions.covers(finding.rule, path)
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, *arguments)))


def parameters(arguments: ast.arguments) -> FrozenList[ast.arg]:
    return FrozenList((
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *filter(None, (arguments.vararg, arguments.kwarg)),
    ))


def unquoted(text: str) -> Iterator[ast.expr]:
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError:
        return
    yield parsed.body


def dotted(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            base = dotted(value)
            return f"{base}.{attribute}" if base is not None else None
        case _:
            return None


def name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return name_of(node.func)
    found = dotted(node)
    return found.rpartition(".")[2] if found is not None else None


def source(path: str) -> Source:
    parts = PurePosixPath(posix(path)).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    package = bool(parts) and parts[-1] == "__init__"
    return Source(".".join(parts[:-1] if package else parts), package=package)


def resolve(node: ast.ImportFrom, origin: Source) -> str:
    if node.level == 0:
        return str(node.module)
    base = origin.module if origin.package else origin.module.rpartition(".")[0]
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    return ".".join(part for part in (base, node.module) if part)
