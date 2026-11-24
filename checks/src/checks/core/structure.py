import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
from checks.core.immutability import parameters
from checks.core.values import Inputs, Outcome, Request, posix, summarized

if TYPE_CHECKING:
    from collections.abc import Container, Iterator, Sequence

type Function = ast.FunctionDef | ast.AsyncFunctionDef

RECEIVERS = FrozenOrderedSet(("self", "cls"))


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    advice: str


TRIVIAL_WRAPPER = Rule("STR001", "adds no behaviour; inline it")


@dataclass(frozen=True, slots=True)
class Definition:
    name: str
    node: Function | ast.ClassDef
    method: bool
    inherits: bool


@dataclass(frozen=True, slots=True)
class Module:
    path: str
    name: str
    imports: FrozenOrderedDict[str, str]
    definitions: FrozenList[Definition]


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: Rule
    message: str


def package(directory: PurePosixPath, paths: Container[str]) -> FrozenList[str]:
    if not directory.name or str(directory / "__init__.py") not in paths:
        return FrozenList()
    return FrozenList((*package(directory.parent, paths), directory.name))


def imported(
    statement: ast.stmt, parts: Sequence[str]
) -> Iterator[tuple[str, str]]:
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            root = alias.name.split(".", 1)[0]
            yield (alias.asname, alias.name) if alias.asname else (root, root)
    if isinstance(statement, ast.ImportFrom):
        base = (
            parts[: len(parts) + 1 - statement.level] if statement.level else ()
        )
        origin = ".".join((*base, *filter(None, (statement.module,))))
        for alias in statement.names:
            name = f"{origin}.{alias.name}" if origin else alias.name
            yield alias.asname or alias.name, name


def definitions(
    body: Sequence[ast.stmt],
    owner: str,
    *,
    method: bool = False,
    inherits: bool = False,
) -> Iterator[Definition]:
    for statement in body:
        if isinstance(statement, ast.ClassDef):
            name = f"{owner}.{statement.name}"
            yield Definition(name, statement, method, inherits)
            yield from definitions(
                statement.body,
                name,
                method=True,
                inherits=bool(statement.bases or statement.keywords),
            )
        elif isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            name = f"{owner}.{statement.name}"
            yield Definition(name, statement, method, inherits)
            yield from definitions(statement.body, name)


def parsed(path: str, text: str, paths: Container[str]) -> Module:
    tree = ast.parse(text, filename=path)
    file = PurePosixPath(posix(path))
    parts = package(file.parent, paths)
    name = (
        ".".join(parts) or file.parent.name
        if file.name == "__init__.py"
        else ".".join((*parts, file.stem))
    )
    imports = FrozenOrderedDict(
        pair for statement in tree.body for pair in imported(statement, parts)
    )
    return Module(path, name, imports, FrozenList(definitions(tree.body, name)))


def dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def candidates(name: str, module: Module) -> Iterator[str]:
    root, _, rest = name.partition(".")
    origin = module.imports.get(root)
    if origin is None:
        yield name
    else:
        yield f"{origin}.{rest}" if rest else origin
    if not rest:
        yield f"{module.name}.{name}"


def returned(function: Function) -> ast.expr | None:
    statements = FrozenList(
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    )
    match statements:
        case (ast.Return(value=value),):
            return value
        case _:
            return None


def forwarded(definition: Definition, function: Function) -> FrozenList[str]:
    return FrozenList(
        parameter.arg
        for parameter in parameters(function.args)
        if not (definition.method and parameter.arg in RECEIVERS)
    )


def calls_through(
    value: ast.Call,
    definition: Definition,
    module: Module,
    symbols: Container[str],
) -> bool:
    name = dotted(value.func)
    target = (
        None
        if name is None
        else next((c for c in candidates(name, module) if c in symbols), None)
    )
    return target is not None and target != definition.name


def kept(definition: Definition, function: Function) -> bool:
    name = function.name
    return (
        bool(function.decorator_list)
        or (name.startswith("__") and name.endswith("__"))
        or (definition.method and definition.inherits)
    )


def passes_exactly(call: ast.Call, names: Sequence[str]) -> bool:
    arguments = FrozenList(
        argument.id for argument in call.args if isinstance(argument, ast.Name)
    )
    return (
        bool(names)
        and not call.keywords
        and len(arguments) == len(call.args)
        and sorted(arguments) == sorted(names)
    )


def trivial_wrapper(
    definition: Definition,
    function: Function,
    module: Module,
    symbols: Container[str],
) -> Finding | None:
    value = returned(function)
    names = forwarded(definition, function)
    wraps = (isinstance(value, ast.Name) and value.id in names) or (
        isinstance(value, ast.Call)
        and passes_exactly(value, names)
        and calls_through(value, definition, module, symbols)
    )
    if kept(definition, function) or not wraps:
        return None
    rule = TRIVIAL_WRAPPER
    message = f"`{function.name}` {rule.advice}"
    return Finding(function.lineno, function.col_offset, rule, message)


def function_findings(
    definition: Definition, module: Module, symbols: Container[str]
) -> Iterator[Finding]:
    function = definition.node
    if isinstance(function, ast.ClassDef):
        return
    yield from filter(
        None, (trivial_wrapper(definition, function, module, symbols),)
    )


def check(
    module: Module, symbols: Container[str], exceptions: Exceptions
) -> FrozenList[Finding]:
    findings = (
        finding
        for definition in module.definitions
        for finding in function_findings(definition, module, symbols)
    )
    return FrozenList(
        finding
        for finding in sorted(findings, key=lambda f: (f.line, f.column))
        if not exceptions.covers(finding.rule.code, module.path)
    )


def describe(path: str, finding: Finding) -> str:
    location = f"{path}:{finding.line}:{finding.column + 1}"
    return f"{location}: {finding.rule.code} {finding.message}"


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, *arguments)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    paths = FrozenOrderedSet(posix(path) for path in arguments)
    modules = FrozenList(
        parsed(path, inputs.texts[path], paths) for path in arguments
    )
    symbols = FrozenOrderedSet(
        definition.name
        for module in modules
        for definition in module.definitions
    )
    return summarized(
        FrozenList(
            describe(module.path, finding)
            for module in modules
            for finding in check(module, symbols, exceptions)
        )
    )
