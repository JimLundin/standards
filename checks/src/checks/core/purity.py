import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    entries,
    parse_toml,
    summarized,
    table,
    within,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

PURE_MODULES = FrozenOrderedSet((
    "__future__",
    "abc",
    "ast",
    "base64",
    "binascii",
    "bisect",
    "calendar",
    "cmath",
    "collections",
    "contextlib",
    "copy",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "enum",
    "fnmatch",
    "fractions",
    "functools",
    "graphlib",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "math",
    "numbers",
    "operator",
    "ordered",
    "random",
    "re",
    "shlex",
    "statistics",
    "string",
    "struct",
    "textwrap",
    "tomllib",
    "types",
    "typing",
    "unicodedata",
    "urllib.parse",
    "uuid",
    "zlib",
))
PURE_NAMES = FrozenOrderedSet((
    "io.StringIO",
    "pathlib.PurePath",
    "pathlib.PurePosixPath",
    "pathlib.PureWindowsPath",
    "tokenize.COMMENT",
    "tokenize.TokenError",
    "tokenize.generate_tokens",
))
EFFECT_BUILTINS = FrozenOrderedSet((
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "globals",
    "help",
    "input",
    "open",
    "quit",
))
EFFECT_TYPES = FrozenOrderedSet((
    "AsyncGenerator",
    "AsyncIterable",
    "AsyncIterator",
    "Awaitable",
    "BinaryIO",
    "Callable",
    "Coroutine",
    "Generator",
    "IO",
    "Iterable",
    "Iterator",
    "TextIO",
    "Type",
    "type",
))
PORT_BASES = FrozenOrderedSet(("ABC", "Protocol"))
LAYER = re.compile(r"[\w.]+")
AWAIT_IN_THE_SHELL = "make it a plain `def` and await in the shell"
SHELL_EFFECT = "call it in the shell and pass its result into the core"
ONLY_DATA = (
    "fix: take the plain values it would give, and keep it in the shell, or,"
    " if it can't apply, a `PUR003` exception with its reason"
)


@dataclass(frozen=True, slots=True)
class Source:
    module: str
    package: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: str
    message: str


def core_modules(pyproject: str | None) -> FrozenList[str]:
    data = parse_toml(pyproject)
    contracts = entries(
        table(table(data.get("tool")).get("importlinter")).get("contracts")
    )
    return FrozenList(
        f"{container}.{name}"
        for contract in contracts
        if table(contract).get("type") == "layers"
        for layers in (entries(table(contract).get("layers")),)
        if layers
        for container in entries(table(contract).get("containers"))
        for found in LAYER.finditer(str(layers[-1]))
        for name in (found[0],)
    )


def source(path: str) -> Source:
    parts = PurePosixPath(path).with_suffix("").parts
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


def imported(
    tree: ast.Module, origin: Source
) -> Iterator[tuple[ast.stmt, str, FrozenList[str]]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (
                (node, alias.name, FrozenList()) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = resolve(node, origin)
            members = FrozenList(
                f"{module}.{alias.name}" for alias in node.names
            )
            yield node, module, members


def import_findings(
    tree: ast.Module, origin: Source, cores: Sequence[str]
) -> Iterator[Finding]:
    yield from (
        Finding(
            node.lineno,
            node.col_offset,
            f"PUR001:{name}",
            (
                f"the core imports `{name}`; fix: import it in the shell and"
                f" pass its results into the core, or, if `{name}` is pure, a"
                f" `PUR001:{name}` exception with its reason"
            ),
        )
        for node, name, members in imported(tree, origin)
        if not within(name, (*PURE_MODULES, *cores))
        and not (members and all(member in PURE_NAMES for member in members))
    )


def builtin_findings(tree: ast.Module) -> Iterator[Finding]:
    yield from (
        Finding(
            node.lineno,
            node.col_offset,
            "PUR002",
            f"the core uses the builtin `{node.id}`; fix: {SHELL_EFFECT}",
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in EFFECT_BUILTINS
    )


def base_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else None


def ports(tree: ast.Module) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and (
            any(base_name(base) in PORT_BASES for base in node.bases)
            or any(
                keyword.arg == "metaclass"
                and base_name(keyword.value) == "ABCMeta"
                for keyword in node.keywords
            )
        )
    )


def names(annotation: ast.expr | None) -> Iterator[str]:
    if annotation is None:
        return
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                yield from names(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                continue
        name = base_name(node)
        if name:
            yield name


def is_public(name: str) -> bool:
    return not name.startswith("_") or (
        name.startswith("__") and name.endswith("__")
    )


def parameters(node: ast.FunctionDef) -> Iterator[ast.expr | None]:
    arguments = node.args
    every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    yield from (argument.annotation for argument in every)
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            yield extra.annotation


def bounds(node: ast.FunctionDef | ast.ClassDef) -> Iterator[ast.expr | None]:
    for parameter in node.type_params:
        if isinstance(parameter, ast.TypeVar):
            yield parameter.bound


def api_inputs(
    body: Sequence[ast.stmt], *, in_class: bool = False
) -> Iterator[tuple[str, ast.stmt, Iterator[ast.expr | None]]]:
    for node in body:
        if isinstance(node, ast.FunctionDef) and is_public(node.name):
            yield node.name, node, iter((*parameters(node), *bounds(node)))
        elif isinstance(node, ast.ClassDef) and is_public(node.name):
            yield node.name, node, bounds(node)
            yield from api_inputs(node.body, in_class=True)
        elif (
            in_class
            and isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and is_public(node.target.id)
        ):
            yield node.target.id, node, iter((node.annotation,))


def api_findings(
    tree: ast.Module, local_ports: FrozenOrderedSet[str]
) -> Iterator[Finding]:
    forbidden = EFFECT_TYPES | local_ports
    for name, node, annotations in api_inputs(tree.body):
        taken = dict.fromkeys(
            found
            for annotation in annotations
            for found in names(annotation)
            if found in forbidden
        )
        yield from (
            Finding(
                node.lineno,
                node.col_offset,
                "PUR003",
                f"`{name}` takes `{found}`; {ONLY_DATA}",
            )
            for found in taken
        )
    yield from (
        Finding(
            node.lineno,
            node.col_offset,
            "PUR003",
            f"`{node.name}` is async; fix: {AWAIT_IN_THE_SHELL}",
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    )


def check(
    trees: Mapping[str, ast.Module],
    cores: Sequence[str],
    exceptions: Exceptions,
) -> Iterator[str]:
    local_ports = FrozenOrderedSet(
        name for tree in trees.values() for name in ports(tree)
    )
    for path, tree in trees.items():
        findings = (
            *import_findings(tree, source(path), cores),
            *builtin_findings(tree),
            *api_findings(tree, local_ports),
        )
        yield from (
            f"{path}:{finding.line}:{finding.column + 1}: {finding.rule.partition(':')[0]} {finding.message}"
            for finding in sorted(findings, key=lambda f: (f.line, f.column))
            if not exceptions.covers(finding.rule, path)
        )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList(("pyproject.toml", EXCEPTIONS, *arguments)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    cores = core_modules(inputs.texts.get("pyproject.toml"))
    trees = FrozenOrderedDict(
        (path, ast.parse(inputs.texts[path], filename=path))
        for path in arguments
        if within(source(path).module, cores)
    )
    return summarized(FrozenList(check(trees, cores, exceptions_in(inputs))))
