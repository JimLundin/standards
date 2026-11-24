import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import exceptions_in
from checks.core.python_source import (
    Finding,
    Rule,
    Source,
    dotted,
    parameters,
    reported,
    resolve,
    source,
)
from checks.core.values import Inputs, Outcome, summarized

if TYPE_CHECKING:
    from collections.abc import Container, Iterator, Sequence

type Function = ast.FunctionDef | ast.AsyncFunctionDef

RECEIVERS = FrozenOrderedSet(("self", "cls"))


TRIVIAL_WRAPPER = Rule("STR001", "adds no behaviour; inline it")
COGNITIVE_COMPLEXITY = Rule("STR002", "flatten it")
COGNITIVE_LIMIT = 10


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


def modules_imported(statement: ast.Import) -> Iterator[tuple[str, str]]:
    for alias in statement.names:
        root = alias.name.split(".", 1)[0]
        yield (alias.asname, alias.name) if alias.asname else (root, root)


def names_imported(
    statement: ast.ImportFrom, origin: Source
) -> Iterator[tuple[str, str]]:
    resolved = resolve(statement, origin)
    for alias in statement.names:
        name = f"{resolved}.{alias.name}" if resolved else alias.name
        yield alias.asname or alias.name, name


def imported(statement: ast.stmt, origin: Source) -> Iterator[tuple[str, str]]:
    match statement:
        case ast.Import():
            yield from modules_imported(statement)
        case ast.ImportFrom():
            yield from names_imported(statement, origin)
        case _:
            pass


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


def parsed(path: str, text: str) -> Module:
    tree = ast.parse(text, filename=path)
    origin = source(path)
    imports = FrozenOrderedDict(
        pair for statement in tree.body for pair in imported(statement, origin)
    )
    name = origin.module
    return Module(path, name, imports, FrozenList(definitions(tree.body, name)))


def candidates(name: str, module: Module) -> Iterator[str]:
    root, _, rest = name.partition(".")
    if root in module.imports:
        origin = module.imports[root]
        yield f"{origin}.{rest}" if rest else origin
    else:
        yield name
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
        next((c for c in candidates(name, module) if c in symbols), None)
        if name is not None
        else None
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
    return Finding(function.lineno, function.col_offset, rule.code, message)


def scored(nodes: Sequence[ast.AST], nesting: int) -> int:
    return sum(cognitive(node, nesting) for node in nodes)


def clause(body: Sequence[ast.stmt], nesting: int) -> int:
    return 1 + nesting + scored(body, nesting + 1) if body else 0


def alternatives(branch: ast.If, nesting: int) -> int:
    # The tree-sitter grammar scb-check scores makes each `elif` a clause of
    # the first `if`, so a chain stays at one nesting; `ast` reads an `elif`
    # as an `if` in the `else`, told apart from one only by its column.
    match branch.orelse:
        case (ast.If(col_offset=column) as chained,) if (
            column == branch.col_offset
        ):
            heads = (chained.test, *chained.body)
            return (
                1
                + nesting
                + scored(heads, nesting + 1)
                + alternatives(chained, nesting)
            )
        case body:
            return clause(body, nesting)


def flow_break(node: ast.AST, nesting: int) -> int | None:
    match node:
        case ast.If(test=test, body=body):
            heads = (test, *body)
            tail = alternatives(node, nesting + 1)
        case (
            ast.For(target=target, iter=iterable, body=body, orelse=orelse)
            | ast.AsyncFor(
                target=target, iter=iterable, body=body, orelse=orelse
            )
        ):
            heads = (target, iterable, *body)
            tail = clause(orelse, nesting + 1)
        case ast.While(test=test, body=body, orelse=orelse):
            heads = (test, *body)
            tail = clause(orelse, nesting + 1)
        case ast.ExceptHandler() | ast.IfExp():
            heads = FrozenList(ast.iter_child_nodes(node))
            tail = 0
        case _:
            return None
    return 1 + nesting + scored(heads, nesting + 1) + tail


def cognitive(node: ast.AST, nesting: int) -> int:
    match node:
        case ast.BoolOp(values=values):
            return len(values) - 1 + scored(values, nesting)
        case ast.Break() | ast.Continue():
            return 1
        case (
            ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=end)
            | ast.TryStar(
                body=body, handlers=handlers, orelse=orelse, finalbody=end
            )
        ):
            return scored((*body, *handlers, *end), nesting) + clause(
                orelse, nesting
            )
        case _:
            score = flow_break(node, nesting)
            return (
                score
                if score is not None
                else scored(FrozenList(ast.iter_child_nodes(node)), nesting)
            )


def cognitive_complexity(function: Function) -> Finding | None:
    returns = filter(None, (function.returns,))
    parts = (function.args, *function.body, *returns, *function.type_params)
    score = scored(parts, 0)
    if score <= COGNITIVE_LIMIT:
        return None
    rule = COGNITIVE_COMPLEXITY
    message = (
        f"`{function.name}` has cognitive complexity {score},"
        f" above {COGNITIVE_LIMIT}; {rule.advice}"
    )
    return Finding(function.lineno, function.col_offset, rule.code, message)


def function_findings(
    definition: Definition, module: Module, symbols: Container[str]
) -> Iterator[Finding]:
    function = definition.node
    if isinstance(function, ast.ClassDef):
        return
    yield from filter(
        None,
        (
            trivial_wrapper(definition, function, module, symbols),
            cognitive_complexity(function),
        ),
    )


def findings(module: Module, symbols: Container[str]) -> FrozenList[Finding]:
    return FrozenList(
        finding
        for definition in module.definitions
        for finding in function_findings(definition, module, symbols)
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    modules = FrozenList(parsed(path, inputs.texts[path]) for path in arguments)
    symbols = FrozenOrderedSet(
        definition.name
        for module in modules
        for definition in module.definitions
    )
    return summarized(
        FrozenList(
            line
            for module in modules
            for line in reported(
                module.path, findings(module, symbols), exceptions
            )
        )
    )
